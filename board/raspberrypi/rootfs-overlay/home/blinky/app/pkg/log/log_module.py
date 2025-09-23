import time

class LogModule:
    def __init__(self):
        pass

    def printst(self, log: str):
        self.stamp = time.strftime("%H:%M:%S")
        print(f'{self.stamp} {log}')