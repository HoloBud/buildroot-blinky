from log import LogModule
from pathlib import Path
import os
import time
import sounddevice as sd
import soundfile as sf
import numpy as np
import collections
import threading
from typing import Union
import scipy.signal

DEBUG = 0

class AudioModule:
    def __init__(self, silence_timeout: int = 3):
        # The internal logic operates on chunks defined by chunk_ms.
        # The actual number of frames per chunk (blocksize for sounddevice)
        # will depend on the device's actual sample rate.
        self.chunk_ms = 30 # Milliseconds per audio chunk for internal logic (e.g., volume detection)

        self.channels = 1
        self.silence_timeout = silence_timeout # How much silence to consider end of phrase (in seconds)
        self.bytes_per_sample = 2 # For int16 audio

        self.log_ = LogModule()

        # Actual sample rates the hardware devices operate at, determined at runtime
        self.input_device_sample_rate = 0  # Will be updated by check_input_device
        self.output_device_sample_rate = 0 # Will be updated by check_playback_device

        # --- Continuous Monitoring / Phrase Capture Attributes ---
        # Buffer to store incoming audio chunks (at input_device_sample_rate)
        self._monitoring_buffer = collections.deque()
        # Max duration for pre-roll buffer before voice detection
        self._pre_roll_duration_ms = 500
        # This calculation for pre-roll max chunks is now based on chunk_ms,
        # but the actual audio in the buffer will be at the device's native rate.
        self._pre_roll_max_chunks = int(self._pre_roll_duration_ms / self.chunk_ms) 

        # Buffer for the actual phrase being collected after voice detection (at input_device_sample_rate)
        self._phrase_collection_buffer = bytearray() 
        self._is_collecting_phrase = False # True when phrase collection has started after voice detection

        # Threading events and locks for inter-thread communication
        self._monitor_thread = None
        self._stop_monitor_event = threading.Event() # To stop the monitoring thread
        self._voice_detected_event = threading.Event() # Set when voice detected for wait_for_voice_detection
        self._phrase_completed_event = threading.Event() # Set when a phrase ends for record_phrase

        # To protect access to shared buffers and flags between main thread and monitor thread
        self._buffer_lock = threading.Lock()

        # Threshold for volume
        self.db_threshold = -30

    def save_as_wav(self, byte_data: bytearray, filename: str = "tmp/rec.wav"):
        """
        Saves raw audio data to a WAV file.
        The input byte_data is expected to be at self.input_device_sample_rate.
        """
        if self.input_device_sample_rate == 0:
            self.log_.printst("[ERROR] Input device sample rate not set. Cannot save WAV.")
            return False

        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        audio_np = np.frombuffer(byte_data, dtype=np.int16)

        try:
            # Save at the actual input device sample rate
            sf.write(filename, audio_np, self.input_device_sample_rate) 
            self.log_.printst(f"WAV file saved locally to {filename} at {self.input_device_sample_rate}Hz.")
            return True
        except Exception as e:
            self.log_.printst(f"Error saving WAV file with soundfile: {e}")
            return False

    def start_recording(self, device_id=None, store_as_wav: bool = False):
        """
        Starts a recording session that captures audio until silence is detected
        for `self.silence_timeout` seconds.
        The recorded audio is always at self.input_device_sample_rate.
        """
        if self.input_device_sample_rate == 0:
            self.log_.printst("[ERROR] Input device sample rate not configured. Call check_input_device() first. Aborting recording.")
            return False, None

        full_recording_bytes = bytearray() # This buffer will store audio at input_device_sample_rate
        silent_frames = 0
        # Max silent frames calculation based on the chunk_ms, irrespective of actual sample rate
        max_silent_frames = self.silence_timeout * 1000 / self.chunk_ms 
        
        self.log_.printst("Recording...")

        try:
            # Block size for reading from hardware will depend on device_sample_rate
            stream_block_size = int(self.input_device_sample_rate * self.chunk_ms / 1000)
            if stream_block_size == 0: stream_block_size = 1 # Ensure at least 1 frame

            with sd.InputStream(
                samplerate=self.input_device_sample_rate, # Open stream at device's actual rate
                channels=self.channels,
                dtype='int16',
                blocksize=stream_block_size, 
                device=device_id
            ) as stream:
                while True:
                    data_raw, overflowed = stream.read(stream_block_size)

                    if overflowed:
                        self.log_.printst("[WARN] Audio input stream overflowed!")

                    frame_bytes_raw = data_raw.tobytes()
                    
                    # Apply a filter (suggested formula by chAIlan) - operates on raw device rate audio
                    filtered_audio = self.bandpass_filter_bytes(frame_bytes_raw, sr=self.input_device_sample_rate)

                    # Calculate volume of captured audio
                    audio_np_array = np.frombuffer(filtered_audio, dtype=np.int16)
                    amplitude = np.sqrt(np.mean(np.square(audio_np_array.astype(np.float32))))
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) # standard db calculation formula

                    full_recording_bytes.extend(filtered_audio)

                    if (audio_volume > self.db_threshold):
                        silent_frames = 0
                    else:
                        silent_frames += 1
                        if silent_frames >= max_silent_frames:
                            break

        except sd.PortAudioError as e:
            self.log_.printst(f"[ERR] PortAudio Error during recording: {e}")
            return False, None
        except Exception as e:
            self.log_.printst(f"[ERR] Attempt to record audio failed: {e}")
            return False, None

        self.log_.printst("Recording stopped (by timeout).")
        
        if store_as_wav:
            save_success = self.save_as_wav(full_recording_bytes) 
            return save_success, 0 
        else:
            return False, bytes(full_recording_bytes)

    def bandpass_filter_bytes(self, audio_bytes, sr: int, low=300, high=3400) -> bytes:
        """
        Applies bandpass filter to audio in bytes format at the given sample rate (sr).
        Returns filtered audio in bytes.
        """
        # Convert bytes to numpy array (int16)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
        
        # Convert to float32 (-1.0 to 1.0 range)
        audio_float = audio_np.astype(np.float32) / 32768.0
        
        # Design bandpass filter (300-3400Hz for speech)
        nyq = 0.5 * sr
        low_normalized = low / nyq
        high_normalized = high / nyq
        
        # Ensure filter frequencies are within Nyquist limits
        if low_normalized >= 1.0 or high_normalized >= 1.0:
            self.log_.printst(f"[WARN] Bandpass filter frequencies ({low}-{high}Hz) too high for sample rate {sr}Hz. Skipping filter.")
            return audio_bytes # Return original bytes if filter cannot be applied
            
        b, a = scipy.signal.butter(4, [low_normalized, high_normalized], btype='band')
        
        # Apply filter
        filtered = scipy.signal.lfilter(b, a, audio_float)
        
        # Convert back to int16 bytes
        filtered_bytes = (filtered * 32767).astype(np.int16).tobytes()
        
        return filtered_bytes

    def _monitor_audio_input(self, device_id):
        """
        Internal method for continuous audio monitoring in a separate thread.
        Detects voice activity and collects phrases. All internal buffers are at input_device_sample_rate.
        """
        if self.input_device_sample_rate == 0:
            self.log_.printst("[ERROR] Monitor: Input device sample rate not configured. Aborting monitoring thread.")
            return

        self.log_.printst(f"Audio monitoring thread started on device: {device_id if device_id is not None else 'default'} reading at {self.input_device_sample_rate}Hz.")
        
        # Reset internal states for monitoring. Ensure events are cleared before starting the loop.
        self._voice_detected_event.clear()
        self._phrase_completed_event.clear()
        self._is_collecting_phrase = False

        with self._buffer_lock:
            self._monitoring_buffer.clear()
            self._phrase_collection_buffer = bytearray() # Ensure this is clear on start

        silent_frames_since_speech = 0
        max_silent_frames_after_speech = self.silence_timeout * 1000 / self.chunk_ms

        try:
            # Block size for reading from hardware
            stream_block_size = int(self.input_device_sample_rate * self.chunk_ms / 1000)
            if stream_block_size == 0: stream_block_size = 1 # Ensure at least 1 frame

            with sd.InputStream(
                samplerate=self.input_device_sample_rate, # Open stream at device's actual rate
                channels=self.channels,
                dtype='int16',
                blocksize=stream_block_size, 
                device=device_id
            ) as stream:
                is_speech_ctr = 0
                sample_ctr = 0
                phrase_score = 0
                while not self._stop_monitor_event.is_set():
                    data_raw, overflowed = stream.read(stream_block_size)
                    if overflowed:
                        self.log_.printst("[WARN] Monitor: Audio input stream overflowed!")

                    frame_bytes_raw = data_raw.tobytes()
                    sample_ctr += 1

                    # Calculate volume of captured audio
                    audio_np_array = np.frombuffer(frame_bytes_raw, dtype=np.int16)
                    amplitude = np.sqrt(np.mean(np.square(audio_np_array.astype(np.float32))))
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) # standard db calculation formula

                    # This approach works really good against noise
                    if (audio_volume > self.db_threshold):
                        is_speech_ctr += 1

                    # Reset sample_ctr and phrase_score periodically for ongoing detection
                    if (sample_ctr * self.chunk_ms >= 300): # Check speech every 300ms (based on 30ms chunks)
                        sample_ctr = 0
                        is_speech_ctr = 0
                        phrase_score = 0

                    phrase_score += is_speech_ctr

                    with self._buffer_lock: 
                        if phrase_score >= 20: # value based on experimentation with "por que?" vs switch noise
                            silent_frames_since_speech = 0
                            if not self._is_collecting_phrase:
                                # Voice detected, beginning of a new phrase
                                self.log_.printst("Monitor: Voice detected!")
                                self._is_collecting_phrase = True
                                self._voice_detected_event.set() # Signal main thread
                                
                                # Pre-roll buffer is prepended to the phrase collection buffer.
                                # The pre-roll buffer contains audio leading up to the voice detection.
                                self._phrase_collection_buffer.clear()
                                self._phrase_collection_buffer.extend(b''.join(self._monitoring_buffer))
                                self._monitoring_buffer.clear() # Clear pre-roll as it's now part of the phrase
                                if DEBUG: self.log_.printst(f"Monitor: Phrase collection started. Pre-roll buffer added to phrase.")
                            
                            # Extend current phrase with new speech frames (at device's native rate)
                            self._phrase_collection_buffer.extend(frame_bytes_raw)

                        else: # Not speech
                            if self._is_collecting_phrase:
                                # If we were collecting a phrase, and now it's silent
                                silent_frames_since_speech += 1
                                # Continue adding the current silent chunk to the phrase buffer
                                self._phrase_collection_buffer.extend(frame_bytes_raw) 
                                if silent_frames_since_speech >= max_silent_frames_after_speech:
                                    self.log_.printst(f"Monitor: End of phrase detected (silence for {self.silence_timeout}s).")
                                    self._is_collecting_phrase = False # Stop collecting
                                    self._phrase_completed_event.set() # Signal main thread
                                    # Phrase is now complete in _phrase_collection_buffer, it will be retrieved by record_phrase()
                            else:
                                # Not speech and not collecting a phrase (in standby mode)
                                # Keep adding frames to the pre-roll buffer (at device's native rate)
                                self._monitoring_buffer.append(frame_bytes_raw)

        except sd.PortAudioError as e:
            self.log_.printst(f"[ERROR] Monitor: PortAudio Error in audio monitoring: {e}")
        except Exception as e:
            self.log_.printst(f"[ERROR] Monitor: Failed in audio monitoring thread: {e}")
        finally:
            self.log_.printst("Audio monitoring thread stopped.")
            # Ensure events are set if thread terminates unexpectedly
            self._voice_detected_event.set() 
            self._phrase_completed_event.set()
            self._is_collecting_phrase = False # Reset state

    def start_monitoring(self, device_id=None):
        """
        Starts the continuous audio monitoring process in a separate daemon thread.
        Requires check_input_device to be called first to determine self.input_device_sample_rate.
        """
        if self._monitor_thread and self._monitor_thread.is_alive():
            self.log_.printst("Audio monitoring is already active.")
            return

        if self.input_device_sample_rate <= 0:
            self.log_.printst("[ERROR] Input device sample rate not configured. Call check_input_device() first. Aborting monitoring.")
            return

        self.log_.printst("Initializing audio monitoring...")
        self._stop_monitor_event.clear() # Reset stop signal
        
        # Clear phrase buffer and monitoring buffer here when starting monitoring
        # This ensures a clean state before a new monitoring cycle begins.
        with self._buffer_lock:
            self._phrase_collection_buffer = bytearray()
            self._monitoring_buffer.clear()
        
        # Reset voice detection and phrase completion events before starting the thread
        self._voice_detected_event.clear()
        self._phrase_completed_event.clear()
        self._is_collecting_phrase = False # Ensure state is false initially

        self._monitor_thread = threading.Thread(
            target=self._monitor_audio_input,
            args=(device_id,),
            daemon=True # Make thread a daemon so it exits with main program
        )
        self._monitor_thread.start()
        self.log_.printst("Audio monitoring started in background.")

    def stop_monitoring(self):
        """
        Stops the continuous audio monitoring thread.
        """
        if self._monitor_thread and self._monitor_thread.is_alive():
            self.log_.printst("Signaling audio monitoring thread to stop...")
            self._stop_monitor_event.set() # Signal the thread to stop
            self._monitor_thread.join(timeout=5) # Wait for thread to finish
            if self._monitor_thread.is_alive():
                self.log_.printst("[WARN] Audio monitoring thread did not terminate gracefully.")
            self._monitor_thread = None
        else:
            self.log_.printst("Audio monitoring is not active.")

    def wait_for_voice_detection(self, timeout: float = None) -> bool:
        """
        Blocks until voice is detected, or until a timeout occurs.
        Requires start_monitoring() to be called first.

        :param timeout: Maximum time in seconds to wait for voice detection. None for indefinite.
        :return: True if voice was detected, False if timeout or monitoring not active/failed.
        """
        if not (self._monitor_thread and self._monitor_thread.is_alive()):
            self.log_.printst("[ERROR] Monitoring not active. Call start_monitoring() first.")
            return False
        
        if DEBUG: self.log_.printst("Waiting for voice detection...")
        
        # Do NOT clear _phrase_collection_buffer here.
        # It's managed by the monitoring thread and should contain the start of the phrase
        # including the pre-roll when voice is detected.
        # We only clear the voice_detected_event, as this method is about *waiting* for *new* detection.
        self._voice_detected_event.clear()
        self._phrase_completed_event.clear() # Clear phrase completion event as we are waiting for a new phrase

        # Wait for the event to be set by the monitoring thread
        voice_detected = self._voice_detected_event.wait(timeout=timeout)
        
        if voice_detected:
            if DEBUG: self.log_.printst("[OK] Voice detected!")
            # No need to clear buffers here. The monitoring thread handles populating and clearing
            # _monitoring_buffer and prepending it to _phrase_collection_buffer upon detection.
            # _phrase_collection_buffer will be reset in record_phrase after being retrieved.
        else:
            if DEBUG: self.log_.printst("[WARN] Timeout waiting for voice detection or monitoring stopped.")
            # If timeout, reset state to avoid partial phrase collection issues.
            # Clear internal buffers as no phrase was successfully initiated/completed.
            with self._buffer_lock:
                self._is_collecting_phrase = False
                self._monitoring_buffer.clear()
                self._phrase_collection_buffer = bytearray()
            # Clear events again in case they were set just as timeout occurred
            self._voice_detected_event.clear()
            self._phrase_completed_event.clear()

        return voice_detected

    def record_phrase(self, store_as_wav: bool = False, timeout: float = None) -> tuple[bool, Union[bytes, int]]:
        """
        Blocks until a complete phrase (speech followed by silence) is detected
        by the monitoring thread or a timeout occurs.
        The captured phrase is always returned at self.input_device_sample_rate.
        
        :param store_as_wav: If True, saves the phrase to a WAV file and returns (True, 0).
                             If False, returns (False, recorded_bytes).
        :param timeout: Maximum time in seconds to wait for the phrase to complete. None for indefinite.
        :return: A tuple (success_status, audio_data).
                 If store_as_wav is True: (True/False for save success, 0).
                 If store_as_wav is False: (False, recorded_bytes).
                 Returns (False, None) on error or timeout if no valid data was collected.
        """
        if not (self._monitor_thread and self._monitor_thread.is_alive()):
            self.log_.printst("[ERROR] Monitoring not active. Call start_monitoring() first.")
            return False, None

        # Check if phrase collection is already active or voice was detected.
        # This helps ensure record_phrase is called after voice detection.
        if not self._is_collecting_phrase and not self._voice_detected_event.is_set():
             self.log_.printst("[WARN] No voice detected yet or phrase collection not active. Waiting for phrase completion may hang or return empty.")

        self.log_.printst("Waiting for phrase to complete...")
        
        # Ensure phrase_completed_event is clear before waiting on it for a new phrase
        self._phrase_completed_event.clear() 

        phrase_completed = self._phrase_completed_event.wait(timeout=timeout)

        if phrase_completed:
            self.log_.printst("[OK] Phrase completed!")
            with self._buffer_lock: # Safely retrieve the collected phrase
                phrase_bytes = bytes(self._phrase_collection_buffer) # Already at input_device_sample_rate
                self._phrase_collection_buffer = bytearray() # Clear for next phrase capture
                
                # Reset these events for the *next* cycle of voice detection/phrase collection
                self._voice_detected_event.clear() 
                self._phrase_completed_event.clear() 
                self._is_collecting_phrase = False # Ensure collection state is reset

            if not phrase_bytes: # Handle cases where phrase_bytes might be empty despite event set
                self.log_.printst("[WARN] Captured phrase was empty.")
                return False, None

            if store_as_wav:
                save_success = self.save_as_wav(phrase_bytes)
                return save_success, 0 
            else:
                return False, phrase_bytes 

        else:
            self.log_.printst("[WARN] Timeout waiting for phrase completion or monitoring stopped.")
            # If timeout, clear any partially collected phrase and reset state for next attempt
            with self._buffer_lock:
                self._phrase_collection_buffer = bytearray()
                self._is_collecting_phrase = False # Reset collecting state on timeout
            # Clear events for next cycle
            self._voice_detected_event.clear()
            self._phrase_completed_event.clear()
            return False, None # Return (False, None) to indicate failure/timeout with no data

    def _try_open_stream(self, device_id: int, is_input: bool, samplerate: int) -> bool:
        """
        Internal helper to attempt opening an audio stream at a specific sample rate
        to check device compatibility without keeping the stream open.
        Returns True on success, False on known sample rate incompatibility. Raises other errors.
        """
        try:
            # Blocksize for testing stream compatibility (based on chunk_ms and test samplerate)
            temp_block_size = int(samplerate * self.chunk_ms / 1000)
            if temp_block_size == 0: # Ensure blocksize is at least 1
                temp_block_size = 1

            if is_input:
                stream = sd.InputStream(
                    samplerate=samplerate,
                    channels=self.channels,
                    dtype='int16',
                    blocksize=temp_block_size,
                    device=device_id
                )
            else:
                stream = sd.OutputStream(
                    samplerate=samplerate,
                    channels=1, 
                    dtype='int16',
                    blocksize=temp_block_size,
                    device=device_id
                )
            stream.close() 
            return True
        except sd.PortAudioError as e:
            if "Invalid sample rate" in str(e) or "Input/output sample rate mismatch" in str(e) or "Sample rate not supported" in str(e):
                return False 
            raise # Re-raise other PortAudio errors as they might be critical
        except Exception as e:
            self.log_.printst(f"Unexpected error trying to open stream at {samplerate}Hz: {e}")
            raise 

    def check_input_device(self, device_id=None, test_duration_sec: int = 6) -> bool:
        """
        Checks the availability and sample rate compatibility of the specified input audio device.
        Sets `self.input_device_sample_rate` to the actual rate the device operates at.
        Performs a brief voice detection test.
        """
        self.log_.printst(f"--- Checking Input Device ---")
        
        try:
            selected_device_id = device_id if device_id is not None else sd.default.device[0]

            if selected_device_id is None or selected_device_id == -1:
                self.log_.printst("[ERROR] No input device configured or system default not found.")
                return False

            device_info = sd.query_devices(selected_device_id)
            if device_info['max_input_channels'] == 0:
                self.log_.printst(f"[ERROR] Device #{selected_device_id} '{device_info['name']}' is not an input device.")
                return False
            
            # --- Determine input_device_sample_rate ---
            preferred_sample_rate = 16000 # Your server's preferred rate
            self.log_.printst(f"[INFO] Attempting to open input device '{device_info['name']}' (ID: {selected_device_id}) at {preferred_sample_rate}Hz (preferred rate for server)...")
            
            # Try with your preferred 16kHz first
            if self._try_open_stream(selected_device_id, is_input=True, samplerate=preferred_sample_rate):
                self.input_device_sample_rate = preferred_sample_rate
                self.log_.printst(f"[OK] Input device '{device_info['name']}' configured to use {self.input_device_sample_rate}Hz directly.")
            else: 
                # Fallback strategy: Try higher common rates, then device default
                fallback_samplerate = int(device_info['default_samplerate'])
                self.log_.printst(f"[WARN] Fallback: Device '{device_info['name']}' does not support {preferred_sample_rate}Hz. Trying alternatives.")
                
                # Try higher rates first that are common and hopefully supported, then the device default
                # This list ensures we try rates >= 16kHz, preferring higher if 16kHz isn't supported.
                rates_to_try = sorted(list(set([48000, 44100, preferred_sample_rate, fallback_samplerate])), reverse=True) 
                
                found_compatible_rate = False
                for rate in rates_to_try:
                    # We prioritize rates >= preferred_sample_rate first, but allow fallback_samplerate if it's the only option.
                    if rate >= preferred_sample_rate and self._try_open_stream(selected_device_id, is_input=True, samplerate=rate):
                        self.input_device_sample_rate = rate
                        self.log_.printst(f"[OK] Input device '{device_info['name']}' configured to use {self.input_device_sample_rate}Hz (closest or higher to {preferred_sample_rate}kHz).")
                        found_compatible_rate = True
                        break
                
                if not found_compatible_rate:
                    # If no rate >= preferred_sample_rate worked, try the device's default rate if it wasn't already tried.
                    if self.input_device_sample_rate == 0 and self._try_open_stream(selected_device_id, is_input=True, samplerate=fallback_samplerate):
                        self.input_device_sample_rate = fallback_samplerate
                        self.log_.printst(f"[OK] Input device '{device_info['name']}' configured to use {self.input_device_sample_rate}Hz (using device default as no higher rate supported).")
                    else:
                        self.log_.printst(f"[ERROR] Critical: Device '{device_info['name']}' failed to open at any tested compatible rate.")
                        self.input_device_sample_rate = 0 # Reset to invalid
                        return False
            
            # --- Perform a brief voice detection test (audio not resampled for this test) ---
            stream_block_size = int(self.input_device_sample_rate * self.chunk_ms / 1000)
            if stream_block_size == 0: stream_block_size = 1 # Ensure at least 1 frame

            with sd.InputStream(
                samplerate=self.input_device_sample_rate, 
                channels=self.channels,
                dtype='int16',
                blocksize=stream_block_size,
                device=selected_device_id
            ) as stream:
                self.log_.printst("Please speak now for the voice detection test (max 6 seconds)...")
                start_time = time.time()
                sound_detected = False
                
                while time.time() - start_time < test_duration_sec:
                    data_raw, overflowed = stream.read(stream_block_size)
                    if overflowed:
                        self.log_.printst("Input stream overflowed during test!")

                    frame_bytes_raw = data_raw.tobytes()
                    # Calculate volume of captured audio
                    audio_np_array = np.frombuffer(frame_bytes_raw, dtype=np.int16)
                    amplitude = np.sqrt(np.mean(np.square(audio_np_array.astype(np.float32))))
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) 

                    if audio_volume > self.db_threshold:
                        sound_detected = True
                        break 

                if sound_detected:
                    self.log_.printst("[OK] Test passed: Voice detected on input microphone.")
                    return True
                else:
                    self.log_.printst("[WARN] Couldn't detect voice on input microphone within 6 seconds.")
                    return True # Microphone is technically working even if no voice was heard

        except Exception as e:
            self.log_.printst(f"[ERROR] Failed to check input device: {e}")
            self.log_.printst(f"[FAIL] Input device test failed for device ID {device_id if device_id is not None else 'default'}.")
            self.input_device_sample_rate = 0 # Ensure it's reset on failure
            return False

    def check_playback_device(self, device_id=None) -> bool:
        """
        Checks the availability and compatibility of the specified output audio device.
        Sets `self.output_device_sample_rate` to the actual rate the device operates at.
        Plays a series of test beeps.
        """
        self.log_.printst(f"--- Checking Playback Device ---")
        
        try:
            selected_device_id = device_id if device_id is not None else sd.default.device[1]

            if selected_device_id is None or selected_device_id == -1:
                self.log_.printst("[ERROR] No output device configured or system default not found.")
                return False

            device_info = sd.query_devices(selected_device_id)
            if device_info['max_output_channels'] == 0:
                self.log_.printst(f"[ERROR] Device #{selected_device_id} '{device_info['name']}' is not an output device.")
                return False

            # --- Determine output_device_sample_rate ---
            # For output, 16kHz is also a good preferred target as it aligns with common speech processing.
            preferred_sample_rate = 16000 
            self.log_.printst(f"[INFO] Attempting to open output device '{device_info['name']}' (ID: {selected_device_id}) at {preferred_sample_rate}Hz (preferred rate)...")
            
            if self._try_open_stream(selected_device_id, is_input=False, samplerate=preferred_sample_rate):
                self.output_device_sample_rate = preferred_sample_rate
                self.log_.printst(f"[OK] Output device '{device_info['name']}' configured to use {self.output_device_sample_rate}Hz directly.")
            else: 
                fallback_samplerate = int(device_info['default_samplerate'])
                self.log_.printst(f"[WARN] Fallback: Output device '{device_info['name']}' does not support {preferred_sample_rate}Hz. Trying alternatives.")
                
                rates_to_try = sorted(list(set([48000, 44100, preferred_sample_rate, fallback_samplerate])), reverse=True)
                
                found_compatible_rate = False
                for rate in rates_to_try:
                    if rate >= preferred_sample_rate and self._try_open_stream(selected_device_id, is_input=False, samplerate=rate):
                        self.output_device_sample_rate = rate
                        self.log_.printst(f"[OK] Output device '{device_info['name']}' configured to use {self.output_device_sample_rate}Hz (closest or higher to {preferred_sample_rate}kHz).")
                        found_compatible_rate = True
                        break

                if not found_compatible_rate:
                     if self.output_device_sample_rate == 0 and self._try_open_stream(selected_device_id, is_input=False, samplerate=fallback_samplerate):
                        self.output_device_sample_rate = fallback_samplerate
                        self.log_.printst(f"[OK] Output device '{device_info['name']}' configured to use {self.output_device_sample_rate}Hz (using device default as no higher rate supported).")
                     else:
                        self.log_.printst(f"[ERROR] Critical: Output device '{device_info['name']}' failed to open at any tested compatible rate.")
                        self.output_device_sample_rate = 0 # Reset to invalid
                        return False
            
            # --- Play test beeps (generated at output_device_sample_rate) ---
            stream_block_size = int(self.output_device_sample_rate * self.chunk_ms / 1000)
            if stream_block_size == 0: stream_block_size = 1

            with sd.OutputStream(
                samplerate=self.output_device_sample_rate, 
                channels=1, 
                dtype='int16',
                blocksize=stream_block_size,
                device=selected_device_id
            ) as stream:
                self.log_.printst("Playing test beeps...")

                for i in range(3):
                    frequency = 800 + i * 200 
                    duration = 0.2 
                    amplitude = 0.5 * np.iinfo(np.int16).max 
                    
                    t = np.linspace(0, duration, int(self.output_device_sample_rate * duration), False)
                    beep = amplitude * np.sin(2 * np.pi * frequency * t)
                    
                    stream.write(beep.astype(np.int16))
                    time.sleep(0.3) 

                self.log_.printst("[OK] Test passed: Beeps played on output device.")
                return True

        except Exception as e:
            self.log_.printst(f"[ERROR] Failed to check playback device: {e}")
            self.log_.printst(f"[FAIL] Playback device test failed for device ID {device_id if device_id is not None else 'default'}.")
            self.output_device_sample_rate = 0 # Ensure it's reset on failure
            return False

    def play_wav(self, filepath, device_id=None):
        """
        Plays an audio WAV file through the specified output device.
        Assumes the input WAV file is 16kHz. Resamples to output device rate if needed.
        """
        if self.output_device_sample_rate == 0:
            self.log_.printst("[ERROR] Output device sample rate not set. Cannot play WAV.")
            return

        try:
            # Read the WAV file using soundfile
            data_np, samplerate_wav = sf.read(filepath, dtype='int16')
            
            data_to_play_np = data_np
            # Only resample if the WAV's sample rate doesn't match the output device's sample rate
            if samplerate_wav != self.output_device_sample_rate:
                self.log_.printst(f"DEBUG: Resampling WAV from {samplerate_wav}Hz to {self.output_device_sample_rate}Hz for output device playback.")
                num_samples = len(data_np)
                # Resampling for playback, ensure it's at output_device_sample_rate
                new_num_samples = int(num_samples * (self.output_device_sample_rate / samplerate_wav))
                resampled_audio_float = scipy.signal.resample(data_np.astype(float), new_num_samples)
                data_to_play_np = resampled_audio_float.astype(np.int16)
            
            # Play 100 ms of silence first (hack for ALSA)
            # This silence should be generated at the actual output device sample rate
            silence = np.zeros(int(0.1 * self.output_device_sample_rate), dtype=np.int16)
            sd.play(silence, self.output_device_sample_rate, blocking=True)

            # Play the audio using sounddevice
            sd.play(data_to_play_np, self.output_device_sample_rate, device=device_id) 
            self.log_.printst(f"WAV file played successfully: {filepath}")

        except FileNotFoundError:
            self.log_.printst(f"Error: WAV file not found at {filepath}")
        except Exception as e:
            self.log_.printst(f"Error playing WAV file: {e}")

    def get_wav_duration(self, filepath) -> float:
        """
        Gets the duration of a WAV file in seconds.
        """
        try:
            info = sf.info(filepath)
            return info.frames / info.samplerate # return in seconds
        except FileNotFoundError:
            self.log_.printst(f"Error: WAV file not found at {filepath}")
            return 0.0
        except Exception as e:
            self.log_.printst(f"Error getting WAV duration: {e}")
            return 0.0

    def play_audio_buffer(self, audio_bytes: bytes, device_id = None) -> float:
        """
        Plays the decoded response buffer through the specified output device.
        Resampling is not needed because the server builds the response based
        on the existent output device sample rate.
        """
        # Check if audio device sample rate is properly set
        if self.output_device_sample_rate == 0:
            self.log_.printst("[ERROR] Output device sample rate not set. Cannot play WAV.")
            return 0.0
        # Check if audio buffer is empty
        if len(audio_bytes) == 0:
            self.log_.printst("[ERROR] Response buffer is empty.")
            return 0.0

        # Convert raw bytes to 16-bit PCM
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
        try:
            # Play 16-bit PCM buffer
            sd.play(audio_data, self.output_device_sample_rate, device=device_id)
        except Exception as e:
            self.log_.printst(f"Error playing buffer: {e}")

        # Return audio buffer duration to not waste time doing it in a separate method
        return (len(audio_data) / self.output_device_sample_rate)

    def get_input_device_sample_rate(self) -> int:
        """
        Returns the actual sample rate the input device is configured to operate at.
        Returns 0 if not yet configured or on error.
        """
        return self.input_device_sample_rate

    def get_output_device_sample_rate(self) -> int:
        """
        Returns the actual sample rate the output device is configured to operate at.
        Returns 0 if not yet configured or on error.
        """
        return self.output_device_sample_rate
