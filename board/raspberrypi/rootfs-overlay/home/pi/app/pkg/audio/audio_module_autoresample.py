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

class AudioModule:
    def __init__(self, silence_timeout: int = 3):
        # Our target internal sample rate for all processed audio (VAD, Vosk, saving WAVs)
        self.sample_rate = 16000    
        
        # Actual sample rates the hardware devices operate at, determined at runtime
        self.input_device_sample_rate = self.sample_rate  # Will be updated by check_input_device
        self.output_device_sample_rate = self.sample_rate # Will be updated by check_playback_device

        # Chunk size for internal processing, ALWAYS based on self.sample_rate (16kHz)
        self.chunk_ms = 30 # Milliseconds per audio chunk for VAD
        self.chunk_size = int(self.sample_rate * self.chunk_ms / 1000) # Number of frames per chunk at 16kHz

        self.channels = 1
        self.silence_timeout = silence_timeout # How much silence to consider end of phrase (in seconds)
        self.bytes_per_sample = 2 # For int16 audio

        self.log_ = LogModule()

        # --- Continuous Monitoring / Phrase Capture Attributes ---
        # Buffer to store incoming audio chunks
        # These buffers will always store audio at self.sample_rate (16kHz)
        self._monitoring_buffer = collections.deque()
        # Max duration for pre-roll buffer before voice detection
        self._pre_roll_duration_ms = 500
        self._pre_roll_max_chunks = int(self._pre_roll_duration_ms / self.chunk_ms)

        # Buffer for the actual phrase being collected after voice detection
        self._phrase_collection_buffer = bytearray() 
        self._is_collecting_phrase = False # True when phrase collection has started after voice detection

        # Threading events and locks for inter-thread communication
        self._monitor_thread = None
        self._stop_monitor_event = threading.Event() # To stop the monitoring thread
        self._voice_detected_event = threading.Event() # Set when VAD detects voice for wait_for_voice_detection
        self._phrase_completed_event = threading.Event() # Set when a phrase ends for record_phrase

        # To protect access to shared buffers and flags between main thread and monitor thread
        self._buffer_lock = threading.Lock()

        # Threshold for volume
        self.db_threshold = -30

    def _resample_audio(self, audio_data: bytes, source_sr: int, target_sr: int) -> bytes:
        """
        Resamples raw audio data (PCM 16-bit) from source_sr to target_sr.
        """
        if source_sr == target_sr:
            return audio_data

        #self.log_.printst(f"DEBUG: Performing audio resampling from {source_sr}Hz to {target_sr}Hz.")
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        num_samples = len(audio_np)
        new_num_samples = int(num_samples * (target_sr / source_sr))

        # Perform resampling using scipy.signal.resample
        resampled_audio_float = scipy.signal.resample(audio_np.astype(float), new_num_samples)
        resampled_audio_np = resampled_audio_float.astype(np.int16)
        return resampled_audio_np.tobytes()

    def save_as_wav(self, byte_data: bytearray, filename: str = "tmp/rec.wav"):
        """
        Saves raw audio data to a WAV file.
        The input byte_data is expected to already be at self.sample_rate (16kHz).
        """
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        
        audio_np = np.frombuffer(byte_data, dtype=np.int16)

        try:
            # Always save at the target internal sample rate (16000 Hz)
            sf.write(filename, audio_np, self.sample_rate) 
            self.log_.printst(f"WAV file saved locally to {filename} at {self.sample_rate}Hz.")
            return True
        except Exception as e:
            self.log_.printst(f"Error saving WAV file with soundfile: {e}")
            return False

    def start_recording(self, device_id=None, store_as_wav: bool = False):
        """
        Starts a recording session that captures audio until silence is detected
        for `self.silence_timeout` seconds.
        The recorded audio is always processed and returned at self.sample_rate (16kHz).
        """
        full_recording_16khz = bytearray() # This buffer will always store 16kHz audio
        silent_frames = 0
        # Max silent frames calculation based on self.sample_rate (16kHz chunk size)
        max_silent_frames = self.silence_timeout * 1000 / self.chunk_ms 
        
        self.log_.printst("Recording...")

        try:
            with sd.InputStream(
                samplerate=self.input_device_sample_rate, # Open stream at device's actual rate
                channels=self.channels,
                dtype='int16',
                # Block size for reading from hardware will depend on device_sample_rate
                # We need to calculate it dynamically here, or use a larger buffer and manually chunk
                # For simplicity, let's calculate a blocksize that gives us a 'chunk_ms' equivalent
                # at the device's rate.
                blocksize=int(self.input_device_sample_rate * self.chunk_ms / 1000), 
                device=device_id
            ) as stream:
                while True:
                    # Read a block of audio data
                    # data is a NumPy array, frames are the actual frames read
                    # overflowed is a boolean indicating if an overflow occurred
                    data_raw, overflowed = stream.read(int(self.input_device_sample_rate * self.chunk_ms / 1000))

                    if overflowed:
                        self.log_.printst("Audio input stream overflowed!")

                    # Convert NumPy array to bytes for VAD and storage
                    frame_bytes_raw = data_raw.tobytes()

                    # Immediately resample to our internal standard (16kHz)
                    frame_bytes_16khz = self._resample_audio(frame_bytes_raw, self.input_device_sample_rate, self.sample_rate)
                    
                    # Apply a filter (suggested formula by chAIlan)
                    filtered_audio = self.bandpass_filter_bytes(frame_bytes_16khz)

                    # Calculate volume of captured audio
                    audio_np_array = np.frombuffer(filtered_audio, dtype=np.int16)
                    amplitude = np.sqrt(np.mean(np.square(audio_np_array.astype(np.float32))))
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) # standard db calculation formula

                    full_recording_16khz.extend(filtered_audio)

                    # VAD check uses the 16kHz resampled frame and self.sample_rate
                    if (audio_volume > self.db_threshold):
                        silent_frames = 0
                    else:
                        silent_frames += 1
                        if silent_frames >= max_silent_frames:
                            break

        except sd.PortAudioError as e:
            self.log_.printst(f"PortAudio Error during recording: {e}")
            return False, None
        except Exception as e:
            self.log_.printst(f"Attempt to record audio failed: {e}")
            return False, None

        self.log_.printst("Recording stopped (by timeout).")
        
        # The recording is already at 16kHz, no further resampling needed for output
        if store_as_wav:
            save_success = self.save_as_wav(full_recording_16khz) 
            return save_success, 0 
        else:
            return False, bytes(full_recording_16khz)

    def bandpass_filter_bytes(self, audio_bytes, sr=16000, low=300, high=3400):
        """
        Applies bandpass filter to 16kHz audio in bytes format.
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
        b, a = scipy.signal.butter(4, [low_normalized, high_normalized], btype='band')
        
        # Apply filter
        filtered = scipy.signal.lfilter(b, a, audio_float)
        
        # Convert back to int16 bytes
        filtered_bytes = (filtered * 32767).astype(np.int16).tobytes()
        
        return filtered_bytes

    def _monitor_audio_input(self, device_id):
        """
        Internal method for continuous audio monitoring in a separate thread.
        Detects voice activity and collects phrases. All internal buffers are 16kHz.
        """
        self.log_.printst(f"Audio monitoring thread started on device: {device_id if device_id is not None else 'default'} reading at {self.input_device_sample_rate}Hz, processing at {self.sample_rate}Hz.")
        
        # Reset internal states for monitoring
        self._voice_detected_event.clear()
        self._phrase_completed_event.clear()
        self._is_collecting_phrase = False

        with self._buffer_lock:
            self._monitoring_buffer.clear()
            self._phrase_collection_buffer = bytearray()

        silent_frames_since_speech = 0
        max_silent_frames_after_speech = self.silence_timeout * 1000 / self.chunk_ms

        try:
            with sd.InputStream(
                samplerate=self.input_device_sample_rate, # Open stream at device's actual rate
                channels=self.channels,
                dtype='int16',
                # Block size for reading from hardware
                blocksize=int(self.input_device_sample_rate * self.chunk_ms / 1000), 
                device=device_id
            ) as stream:
                is_speech_ctr = 0
                sample_ctr = 0
                last_speech_idx = 0
                phrase_score = 0
                while not self._stop_monitor_event.is_set():
                    data_raw, overflowed = stream.read(int(self.input_device_sample_rate * self.chunk_ms / 1000))
                    if overflowed:
                        self.log_.printst("Monitor: Audio input stream overflowed!")

                    frame_bytes_raw = data_raw.tobytes()
                    sample_ctr += 1

                    # Immediately resample to our internal standard (16kHz)
                    frame_bytes_16khz = self._resample_audio(frame_bytes_raw, self.input_device_sample_rate, self.sample_rate)

                    # Apply a filter (suggested formula by chAIlan)
                    filtered_audio = self.bandpass_filter_bytes(frame_bytes_16khz)

                    # Calculate volume of captured audio
                    audio_np_array = np.frombuffer(filtered_audio, dtype=np.int16)
                    amplitude = np.sqrt(np.mean(np.square(audio_np_array.astype(np.float32))))
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) # standard db calculation formula

                    # This approach works really good against noise, webrtcvad does not work at all for detecting speech :S
                    if (audio_volume > self.db_threshold):
                        is_speech_ctr += 1

                    if (sample_ctr == 10): # 300ms
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
                                
                                # Add pre-roll buffer (already 16kHz) to the phrase collection
                                while self._monitoring_buffer:
                                    self._phrase_collection_buffer.extend(self._monitoring_buffer.popleft())
                                self.log_.printst(f"Monitor: Pre-roll buffer added ({len(self._phrase_collection_buffer)} bytes).")
                            
                            # Extend current phrase with new 16kHz speech frames
                            self._phrase_collection_buffer.extend(filtered_audio)

                        else: # Not speech
                            if self._is_collecting_phrase:
                                # If we were collecting a phrase, and now it's silent
                                silent_frames_since_speech += 1
                                if silent_frames_since_speech >= max_silent_frames_after_speech:
                                    self.log_.printst(f"Monitor: End of phrase detected (silence for {self.silence_timeout}s).")
                                    self._is_collecting_phrase = False # Stop collecting
                                    self._phrase_completed_event.set() # Signal main thread
                                    # Phrase is now complete in _phrase_collection_buffer, it will be retrieved by record_phrase()
                                else:
                                    # Continue collecting silence (already 16kHz)
                                    self._phrase_collection_buffer.extend(filtered_audio)
                            else:
                                # Not speech and not collecting a phrase (in standby mode)
                                # Keep adding 16kHz frames to the pre-roll buffer
                                self._monitoring_buffer.append(filtered_audio)
                                if len(self._monitoring_buffer) > self._pre_roll_max_chunks:
                                    self._monitoring_buffer.popleft() # Remove oldest chunk

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

        if self.input_device_sample_rate is None or self.input_device_sample_rate <= 0:
            self.log_.printst("[ERROR] Input device sample rate not configured. Call check_input_device() first. Aborting monitoring.")
            return

        self.log_.printst("Initializing audio monitoring...")
        self._stop_monitor_event.clear() # Reset stop signal
        
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
        
        self.log_.printst("Waiting for voice detection...")
        # Clear the event before waiting to ensure it's not already set from a previous run
        self._voice_detected_event.clear()
        self._phrase_completed_event.clear() # Also clear phrase completion, as we're starting a new detection cycle

        # Wait for the event to be set by the monitoring thread
        voice_detected = self._voice_detected_event.wait(timeout=timeout)
        
        if voice_detected:
            self.log_.printst("[OK] Voice detected!")
        else:
            self.log_.printst("[WARN] Timeout waiting for voice detection or monitoring stopped.")
            # If timeout, reset state to avoid partial phrase collection issues
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
        The captured phrase is always returned at self.sample_rate (16kHz).
        
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

        if not self._is_collecting_phrase and not self._voice_detected_event.is_set():
             self.log_.printst("[WARN] No voice detected yet or phrase collection not active. Waiting for phrase completion may hang.")

        self.log_.printst("Waiting for phrase to complete...")
        
        # Ensure phrase_completed_event is clear before waiting on it for a new phrase
        # It should be cleared by wait_for_voice_detection, or after a phrase completes.
        self._phrase_completed_event.clear() 

        phrase_completed = self._phrase_completed_event.wait(timeout=timeout)

        if phrase_completed:
            self.log_.printst("[OK] Phrase completed!")
            with self._buffer_lock: # Safely retrieve the collected phrase
                phrase_bytes_16khz = bytes(self._phrase_collection_buffer) # Already 16kHz
                self._phrase_collection_buffer = bytearray() # Clear for next phrase
                # Reset event state for next phrase cycle
                self._voice_detected_event.clear() 
                self._phrase_completed_event.clear() 

            if not phrase_bytes_16khz: # Handle cases where phrase_bytes might be empty despite event set
                self.log_.printst("[WARN] Captured phrase was empty.")
                return False, None

            # The phrase is already at 16kHz, no further resampling needed for output from this method
            if store_as_wav:
                save_success = self.save_as_wav(phrase_bytes_16khz)
                return save_success, 0 
            else:
                return False, phrase_bytes_16khz 

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
            # Blocksize for testing stream compatibility
            temp_block_size = int(samplerate * self.chunk_ms / 1000)

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
                    device=device_id
                )
            stream.close() 
            return True
        except sd.PortAudioError as e:
            if "Invalid sample rate" in str(e) or "Input/output sample rate mismatch" in str(e):
                return False 
            raise # Re-raise other PortAudio errors as they might be critical
        except Exception as e:
            self.log_.printst(f"Unexpected error trying to open stream at {samplerate}Hz: {e}")
            raise 

    def check_input_device(self, device_id=None, test_duration_sec: int = 6):
        """
        Checks the availability and sample rate compatibility of the specified input audio device.
        Sets `self.input_device_sample_rate` to the actual rate the device operates at.
        Performs a brief voice detection test after resampling to 16kHz internally.
        """
        self.log_.printst(f"--- Checking Input Device ---")
        
        try:
            # 1. Check if device exists and is usable (initial check)
            selected_device_id = device_id if device_id is not None else sd.default.device[0]

            if selected_device_id is None or selected_device_id == -1:
                self.log_.printst("[ERROR] No input device configured or system default not found.")
                return False

            device_info = sd.query_devices(selected_device_id)
            if device_info['max_input_channels'] == 0:
                self.log_.printst(f"[ERROR] Device #{selected_device_id} '{device_info['name']}' is not an input device.")
                return False
            
            # --- Determine input_device_sample_rate ---
            self.log_.printst(f"[INFO] Attempting to open input device '{device_info['name']}' (ID: {selected_device_id}) at {self.sample_rate}Hz (target internal rate)...")
            
            # Try with our preferred/target internal sample rate first (16000 Hz)
            if self._try_open_stream(selected_device_id, is_input=True, samplerate=self.sample_rate):
                self.input_device_sample_rate = self.sample_rate
                self.log_.printst(f"[OK] Input device '{device_info['name']}' configured to use {self.input_device_sample_rate}Hz directly.")
            else: 
                # Fallback to the device's reported default sample rate
                fallback_samplerate = int(device_info['default_samplerate'])
                self.log_.printst(f"[WARN] Fallback: Device '{device_info['name']}' does not support {self.sample_rate}Hz. Trying {fallback_samplerate}Hz.")
                
                if self._try_open_stream(selected_device_id, is_input=True, samplerate=fallback_samplerate):
                    self.input_device_sample_rate = fallback_samplerate
                    self.log_.printst(f"[OK] Input device '{device_info['name']}' configured to use {self.input_device_sample_rate}Hz (audio will be immediately resampled to {self.sample_rate}Hz internally).")
                else:
                    self.log_.printst(f"[ERROR] Critical: Device '{device_info['name']}' failed to open even at its default rate {fallback_samplerate}Hz.")
                    return False
            
            # --- Perform a brief voice detection test (audio resampled to 16kHz for VAD) ---
            # The blocksize for the actual stream. Read enough frames from hardware to equate to one self.chunk_ms at device rate.
            stream_block_size = int(self.input_device_sample_rate * self.chunk_ms / 1000)
            with sd.InputStream(
                samplerate=self.input_device_sample_rate, # Use the determined device rate for the actual stream
                channels=self.channels,
                dtype='int16',
                blocksize=stream_block_size,
                device=selected_device_id
            ) as stream:
                # This is not truly to detect voice but to validate that the microphone detects sound...
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
                    audio_volume = 20 * np.log10(amplitude / 32768 + 1e-10) # standard db calculation formula

                    # Check if a sound above the valid detection threshold occurred
                    if audio_volume > self.db_threshold:
                        sound_detected = True
                        break # Sound detected, stop early

                if sound_detected:
                    self.log_.printst("[OK] Test passed: Voice detected on input microphone.")
                    return True
                else:
                    self.log_.printst("[WARN] Couldn't detect voice on input microphone within 6 seconds.")
                    # Return True because the mic is available, just no voice detected
                    return True # Microphone is technically working even if no voice was heard

        except Exception as e:
            self.log_.printst(f"[ERROR] Failed to check input device: {e}")
            self.log_.printst(f"[FAIL] Input device test failed for device ID {device_id if device_id is not None else 'default'}.")
            return False

    def check_playback_device(self, device_id=None):
        """
        Checks the availability and compatibility of the specified output audio device.
        Sets `self.output_device_sample_rate` to the actual rate the device operates at.
        Plays a series of test beeps.
        """
        self.log_.printst(f"--- Checking Playback Device ---")
        
        try:
            # 1. Check if device exists and is usable (initial check)
            selected_device_id = device_id if device_id is not None else sd.default.device[1]

            if selected_device_id is None or selected_device_id == -1:
                self.log_.printst("[ERROR] No output device configured or system default not found.")
                return False

            device_info = sd.query_devices(selected_device_id)
            if device_info['max_output_channels'] == 0:
                self.log_.printst(f"[ERROR] Device #{selected_device_id} '{device_info['name']}' is not an output device.")
                return False

            # --- Determine output_device_sample_rate ---
            self.log_.printst(f"[INFO] Attempting to open output device '{device_info['name']}' (ID: {selected_device_id}) at {self.sample_rate}Hz (target internal rate)...")
            
            # Try with our preferred/target internal sample rate first (16000 Hz)
            if self._try_open_stream(selected_device_id, is_input=False, samplerate=self.sample_rate):
                self.output_device_sample_rate = self.sample_rate
                self.log_.printst(f"[OK] Output device '{device_info['name']}' configured to use {self.output_device_sample_rate}Hz directly.")
            else: 
                # Fallback to the device's reported default sample rate
                fallback_samplerate = int(device_info['default_samplerate'])
                self.log_.printst(f"[WARN] Fallback: Output device '{device_info['name']}' does not support {self.sample_rate}Hz. Trying {fallback_samplerate}Hz.")
                
                if self._try_open_stream(selected_device_id, is_input=False, samplerate=fallback_samplerate):
                    self.output_device_sample_rate = fallback_samplerate
                    self.log_.printst(f"[OK] Output device '{device_info['name']}' configured to use {self.output_device_sample_rate}Hz (audio will be resampled from {self.sample_rate}Hz before playback).")
                else:
                    self.log_.printst(f"[ERROR] Critical: Output device '{device_info['name']}' failed to open even at its default rate {fallback_samplerate}Hz.")
                    return False
            
            # --- Play test beeps (generated at output_device_sample_rate) ---
            with sd.OutputStream(
                samplerate=self.output_device_sample_rate, # Use the determined output device rate
                channels=1, # Beep can be mono
                dtype='int16',
                device=selected_device_id
            ) as stream:
                self.log_.printst("Playing test beeps...")

                # Generate and play 3 beeps
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
            return False

    def play_wav(self, filepath, device_id=None):
        """
        Plays an audio WAV file through the specified output device.
        Assumes internal audio is 16kHz. Resamples to output device rate if needed.
        """
        try:
            # Read the WAV file using soundfile
            data_np, samplerate_wav = sf.read(filepath, dtype='int16')
            
            # Step 1: Ensure the WAV file itself is at our internal standard (16kHz)
            data_16khz_bytes = data_np.tobytes()
            if samplerate_wav != self.sample_rate:
                self.log_.printst(f"DEBUG: Resampling input WAV from {samplerate_wav}Hz to {self.sample_rate}Hz for internal processing.")
                data_16khz_bytes = self._resample_audio(data_16khz_bytes, samplerate_wav, self.sample_rate)
            
            # Step 2: Resample from our internal standard (16kHz) to the output device's actual rate
            data_to_play_bytes = data_16khz_bytes
            if self.output_device_sample_rate != self.sample_rate:
                self.log_.printst(f"DEBUG: Resampling 16kHz audio to {self.output_device_sample_rate}Hz for output device playback.")
                data_to_play_bytes = self._resample_audio(data_to_play_bytes, self.sample_rate, self.output_device_sample_rate)
            
            data_to_play_np = np.frombuffer(data_to_play_bytes, dtype=np.int16)

            # Step 3: Play 100 ms of silence first as ALSA is being ALSA and device is not truly ready to play audio
            # So, this is a little hack to warm up the audio system to not chop blinky's output.
            silence = np.zeros(int(0.1 * self.output_device_sample_rate))
            sd.play(silence, self.output_device_sample_rate, blocking=True)

            # Step 4: Play the audio using sounddevice at the output device's determined sample rate
            sd.play(data_to_play_np, self.output_device_sample_rate, device=device_id) 
            self.log_.printst(f"WAV file played successfully: {filepath}")

        except FileNotFoundError:
            self.log_.printst(f"Error: WAV file not found at {filepath}")
        except Exception as e:
            self.log_.printst(f"Error playing WAV file: {e}")

    def get_wav_duration(self, filepath):
        """
        Gets the duration of a WAV file in seconds.
        """
        try:
            info = sf.info(filepath)
            return info.frames / info.samplerate # return in seconds
        except FileNotFoundError:
            self.log_.printst(f"Error: WAV file not found at {filepath}")
            return 0
        except Exception as e:
            self.log_.printst(f"Error getting WAV duration: {e}")
            return 0
