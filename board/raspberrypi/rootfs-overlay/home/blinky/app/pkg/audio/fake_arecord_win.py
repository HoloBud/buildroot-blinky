import sounddevice as sd
import threading
import queue

class FakeArecord:
    """
    Simulates arecord behavior for testing on Windows using sounddevice.
    Provides a .stdout.read(n) interface to mimic subprocess pipes.
    """

    def __init__(self, samplerate=16000, channels=1, chunk_size=4096, device_index=1):
        self.samplerate = samplerate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device_index = device_index
        self._queue = queue.Queue()
        self.stdout = self  # Enables use of .read() just like a real stdout pipe
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._record_loop)

    def start(self):
        """Starts the recording thread."""
        self._thread.start()

    def _record_loop(self):
        """Internal recording loop running in a background thread."""
        def callback(indata, frames, time, status):
            if self._stop.is_set():
                raise sd.CallbackAbort
            self._queue.put(indata.tobytes())

        try:
            with sd.InputStream(samplerate=self.samplerate,
                                channels=self.channels,
                                dtype='int16',
                                blocksize=self.chunk_size,
                                callback=callback,
                                device=(self.device_index, None)):
                self._stop.wait()
        except Exception as e:
            print(f"[ERROR] Failed to open input stream: {e}")

    def read(self, nbytes):
        """
        Mimics .read(nbytes) by pulling audio chunks from the internal queue.
        Blocks until enough data is collected or timeout occurs.
        """
        data = bytearray()
        while len(data) < nbytes:
            try:
                chunk = self._queue.get(timeout=1)
                data.extend(chunk)
            except queue.Empty:
                break
        return bytes(data)

    def terminate(self):
        """Stops the recording thread and closes the stream."""
        self._stop.set()
        self._thread.join()
