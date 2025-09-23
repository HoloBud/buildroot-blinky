import time
from log import LogModule
import base64
import requests
from pathlib import Path
import json
import ssl

POST_REQ = 0
GET_REQ = 1

class WebModule:
    def __init__(self, url: str = "http://34.173.255.203:5000"):
        self.url = url
        self.pub_cert = Path("../../resources/ssl/cert.pem").resolve()

        self.log_ = LogModule()

    def create_error_response(self, response, err: str):
        response.status_code = 501
        response._content = err.encode("utf-8")

    def web_request(self, req_type: int, endpoint: str, payload: str = "", audio_path: str = "", timeout: int = 10):
        headers = {"Content-Type": "application/json"}
        response = requests.Response()
        # POST request
        if req_type == POST_REQ:
            if "process_question" in endpoint:
                try:
                    if audio_path == "":
                        response = requests.post(endpoint, headers=headers, json=payload, timeout=20, verify=self.pub_cert)
                    else:
                        self.log_.printst(f"POST request for {endpoint}")
                        with open(audio_path, 'rb') as audio_file:
                            response = requests.post(endpoint, files={
                                'audio': ('audio.wav', audio_file, 'audio/wav'),
                                'data': ('metadata.json', json.dumps(payload), 'application/json')
                            }, timeout=timeout, verify=self.pub_cert)
                except requests.exceptions.RequestException as e:
                    err_str = f'Request failed: {e}'
                    self.create_error_response(response, err_str)
            elif "register_holo" in endpoint:
                try:
                    response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout, verify=self.pub_cert)
                except requests.exceptions.RequestException as e:
                    err_str = f'Request failed: {e}'
                    self.create_error_response(response, err_str)
        # GET request
        elif req_type == GET_REQ:
            try:
                response = requests.get(endpoint, headers=headers, timeout=timeout, verify=self.pub_cert)
            except requests.exceptions.RequestException as e:
                err_str = f'Request failed: {e}'
                self.create_error_response(response, err_str)
        else:
                err_str = "Unkwnon request type"
                self.create_error_response(response, err_str)

        return response

    def register_hw(self, dev_uuid: str, dev_school: str):
        endpoint = self.url + "/api/v1/register_holo"
        payload = {
            "device_id": dev_uuid,
            "device_school": dev_school,
        }
        return self.web_request(POST_REQ, endpoint, payload)

    def alive(self):
        endpoint = self.url + "/api/v1/alive"
        return self.web_request(GET_REQ, endpoint)

    def voice_processing(self, raw_audio: bytes = 0, audio_file: bool = False, input_sample_rate: int = 16000, output_sample_rate: int = 16000, dev_id: str = "0"):
        endpoint = self.url + "/api/v1/process_question"
        audio_path = ""
        payload = {}

        if audio_file:
            audio_path = Path("tmp/rec.wav").resolve()
            payload = {
                "metadata": {
                    "device_id": dev_id,
                    "i_sample_rate": input_sample_rate,
                    "o_sample_rate": output_sample_rate,
                    "timezone": "America/Mexico_City" # hardcoded for now
                }
            }
        else:
            payload = {
                "data": raw_audio.hex(),
                "metadata": {
                    "device_id": dev_id,
                    "i_sample_rate": input_sample_rate,
                    "o_sample_rate": output_sample_rate,
                    "timezone": "America/Mexico_City" # hardcoded for now
                }
            }

        return self.web_request(POST_REQ, endpoint, payload, audio_path, 20)
