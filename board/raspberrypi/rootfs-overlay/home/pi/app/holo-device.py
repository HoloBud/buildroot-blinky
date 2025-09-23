from log import LogModule
from audio import AudioModule
from web import WebModule
from animations import AnimationHandler, Scene, Character, TriggerAnimationChange
from hologram_fans import HologramFanController, FanModel
from system_config import load_and_apply_config
from alarm_handler import AlarmHandler, AlarmObject, AlarmCyclic, AlarmAction
import json
import sys
import time
import platform
from pathlib import Path
import threading
from enum import Enum
from datetime import datetime, timedelta
import base64
import os

INACTIVITY_TIMEOUT_SECS = 60
DEBUG = True

class Fixed_Audio_Response(Enum):
    ALARM = "alarm"
    BYE = "bye"
    DEVICE_DISABLED = "device_disabled"
    HAPPY = "happy"
    HELLO = "hello"
    NETWORK_ISSUE = "network_issue"
    PII_SCREENER_POSITIVE = "pii_screener_positive"

def get_fixed_audio_response_path(freq : int, fixed_response : Fixed_Audio_Response):
    base_path = Path("..", "..", "resources", "media", "audio", "blinky-fixed-responses")
    file_name = f"{fixed_response.value}_{freq}.wav"
    path = base_path / file_name
    return path

# This IP address is now the static one of the VM instance
server_url = "https://35.208.1.96:443"

log_ = LogModule()

# Load the system configuration
# and automatically CONFIGURE AUDIO DEVICES for subsequent calls
system_config = load_and_apply_config()

# Get relevant configuration parameters
default_behavior = int(system_config.interaction.initial_behavior)
store_hw_on_db = int(system_config.interaction.register_hw)

audio_ = AudioModule(2)

hologram_available = system_config.hardware.hologram_fan_type != FanModel.NO_FAN
if hologram_available:
    hologram_ = HologramFanController(system_config.hardware.hologram_fan_type)
    animationhandler_ = AnimationHandler(hologram_.play_animation)
else:
    def play_animation_dummy(animation_entry: dict, loop_play: bool = False):
        pass
    animationhandler_ = AnimationHandler(play_animation_dummy)

if not audio_.check_playback_device():
    sys.exit(1)
if not audio_.check_input_device():
    sys.exit(1)

# Turn on hologram and greet user
if hologram_available and default_behavior:
    log_.printst("Turning on hologram...")
    hologram_.turn_on()
    time.sleep(2)
    wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.HELLO)
    audio_.play_wav(wavpath)
    animationhandler_.request_animation(Scene.INTRO, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)

# Start listening
audio_.start_monitoring()

# Communicate with server
server = WebModule(server_url)
response = server.alive()

if response.status_code != 200:
    log_.printst("Something is wrong with the server...")
    sys.exit(1)
else:
    log_.printst("Communication with server is fine :)!")

if store_hw_on_db:
    # Register HW in the DB
    response = server.register_hw(system_config.provision.uuid, system_config.provision.school_name)
    if response.status_code != 200:
        print(response)
        log_.printst("HW register failed.")
        sys.exit(1)

alarm_handler_ = AlarmHandler()
alarm_handler_.initialize()
last_alarm_id = None # Keep track of last alarm configured by the user for "undo" functionality

sleep_mode = False
sleep_alarm_id = alarm_handler_.set_up_alarm(datetime.now() + timedelta(seconds=INACTIVITY_TIMEOUT_SECS), AlarmCyclic.NO, AlarmAction.GO_TO_SLEEP_ALARM, "", False)
first_ever_wup = False

# Main loop
while True:
    voice_activated = audio_.wait_for_voice_detection(1) # Blocking call, 1 second timeout

    if voice_activated:
        ###################################################################################################################
        # VOICE PROCESSING LOGIC
        if sleep_mode:
            # Wake up
            if hologram_available:
                hologram_.turn_on()
                time.sleep(2)
            animationhandler_.request_animation(Scene.INTRO, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)
            sleep_mode = False
            last_alarm_id = ""
        else:
            if not default_behavior and not first_ever_wup:
                # First wake up
                if hologram_available:
                    first_ever_wup = True
                    hologram_.turn_on()
                    time.sleep(2)

        # Reproduce listening animation
        animationhandler_.request_animation(Scene.LISTENING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)

        # Record audio
        store_wav = True
        success_save_wav, audio_bytes = audio_.record_phrase(store_as_wav=store_wav)

        # Reproduce searching animation
        animationhandler_.request_animation(Scene.SEARCHING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)

        # Do actual web request
        input_sample_rate = audio_.get_input_device_sample_rate()
        output_sample_rate = audio_.get_output_device_sample_rate()
        # Web request relies on stored recording as WAV file
        response = server.voice_processing(audio_bytes, success_save_wav, input_sample_rate, output_sample_rate, system_config.provision.uuid)

        print(f"status_code = {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            if data.get("status") == "pii_detected":
                wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.PII_SCREENER_POSITIVE)
                duration = audio_.get_wav_duration(wavpath)
                audio_.play_wav(wavpath)
                animationhandler_.request_animation(Scene.PII, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)

            elif data.get("status") == "device_disabled":
                wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.DEVICE_DISABLED)
                duration = audio_.get_wav_duration(wavpath)
                audio_.play_wav(wavpath)
                animationhandler_.request_animation(Scene.SPEAKING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)

            else:
                command = data.get("command")
                if DEBUG: log_.printst(f"Command: {command}")

                if command == "GENERAL_AI_REQUEST":
                    if DEBUG:
                        log_.printst(f"question: {data.get('question')}")
                        log_.printst(f"message: {data.get('message')}")
                    b64_feedbackaudio_string = data.get('feedback_tts_b64')
                    if b64_feedbackaudio_string:
                        try:
                            # Decode the Base64 string into bytes
                            audio_bytes = base64.b64decode(b64_feedbackaudio_string)
                        except Exception as e:
                            log_.printst(f"Error decoding: {e}")
                        
                        # Play decoded audio bytes and animation
                        duration = (audio_.play_audio_buffer(audio_bytes))
                        if DEBUG: log_.printst(f"Animation duration: {duration}")
                        animationhandler_.request_animation(Scene.SPEAKING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)
                    else:
                        log_.printst("Error: Expected WAV file not found on response.")

                elif command == "CMD_GOODBYE":
                    # GOOD BYE
                    alarm_handler_.delete_alarm(sleep_alarm_id)
                    sleep_alarm_id = ""
                    wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.BYE)
                    timetostart,timetoend = animationhandler_.request_animation(Scene.OUTRO, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)
                    time.sleep(timetostart) # To align start of animation with start of sound
                    audio_.play_wav(wavpath)
                    if hologram_available:
                        time.sleep(timetoend-timetostart-0.2) # Wait here for animation to stop, instead of creating a complex timers logic, just wait
                                                            # (-0.2 used to power off hologram before animation ends and device plays next one)
                        hologram_.turn_off()
                    sleep_mode = True

                elif command == "CMD_SET_ALARM":
                    # TIMER/ALARM
                    log_.printst("Alarm processing:")

                    b64_feedbackaudio_string = data.get('feedback_tts_b64')
                    b64_triggeralarmaudio_string = data.get('triggeredalarm_tts_b64')
                    timestamp_str = data.get('datetime')
                    message_str = data.get('message')

                    if (timestamp_str and b64_feedbackaudio_string and b64_triggeralarmaudio_string and message_str):
                        timestamp = datetime.fromisoformat(timestamp_str)
                        try:
                            # Decode the Base64 string into bytes
                            response_audio_bytes = base64.b64decode(b64_feedbackaudio_string)
                            # Decode the Base64 string into bytes
                            alarm_audio_bytes = base64.b64decode(b64_triggeralarmaudio_string)
                            # Write the bytes to a .wav file in binary write mode ('wb')
                            i = 0
                            while os.path.exists(f"alarm{i:05d}.wav"):
                                i = i+1
                            wavfile = f"alarm{i:05d}.wav"
                            with open(wavfile, "wb") as wav_file:
                                wav_file.write(alarm_audio_bytes)
                        
                            last_alarm_id = alarm_handler_.set_up_alarm(timestamp.astimezone(None), AlarmCyclic.NO, AlarmAction.USER_ALARM, message_str, True, wavfile)
                            
                            # Play sound and animation
                            duration = audio_.play_audio_buffer(response_audio_bytes)
                            animationhandler_.request_animation(Scene.SPEAKING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)

                        except Exception as e:
                            log_.printst(f"Error decoding or saving audio: {e}")
                    
                    elif (not timestamp_str and b64_feedbackaudio_string and message_str):
                        # This is how the server sends the Alarm command, when a timestamp could not be determined
                        # We inform the user but the alarm is not set up
                        try:
                            # Decode the Base64 string into bytes
                            audio_bytes = base64.b64decode(b64_feedbackaudio_string)

                            # Play sound and animation
                            duration = audio_.play_audio_buffer(audio_bytes)
                            animationhandler_.request_animation(Scene.SPEAKING, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)
                            
                        except Exception as e:
                            log_.printst(f"Error decoding or saving audio: {e}")
                    
                    else:
                        # Malformed response from server
                        log_.printst("Malformed alarm parameters found on server response")
            
                elif command == "CMD_DELETE_LAST_ALARM":
                    # DELETE LAST ALARM
                    log_.printst("Request to delete last alarm")
                    if last_alarm_id != "":
                        alarm_handler_.delete_alarm(last_alarm_id)
                        last_alarm_id = ""

                elif command == "CMD_DELETE_ALL_ALARMS":
                    # DELETE ALL USER ALARMS
                    log_.printst("Request to delete all alarms")
                    alarm_handler_.clear_all_alarms(True)
                    last_alarm_id = ""

                elif command == "CMD_CURRENT_TIME" or command == "CMD_CURRENT_DATE":
                    # CURRENT DATE/TIME
                    log_.printst("Current date/time request command")
                    b64_feedbackaudio = data.get('feedback_tts_b64')
                    try:
                        # Decode the Base64 string into bytes
                        audio_bytes = base64.b64decode(b64_feedbackaudio)

                        # Play sound and animation
                        duration = audio_.play_audio_buffer(audio_bytes)
                        animationhandler_.request_animation(Scene.TIME, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)

                    except Exception as e:
                        log_.printst(f"Error decoding or saving audio: {e}")
                    
                elif command == "CMD_DANCE":
                    # DELETE ALL USER ALARMS
                    log_.printst("Let's dance")
                    wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.HAPPY)
                    timetostart,timetoend = animationhandler_.request_animation(Scene.HAPPY, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY)
                    time.sleep(timetostart) # To align start of animation with start of sound
                    audio_.play_wav(wavpath)

                else:
                    log_.printst("Unknown command")

                if command != "CMD_SET_ALARM":
                    # Any command other than setting a new alarm, shall forget the "undo last alarm" possibility
                    last_alarm_id = ""

        if not sleep_mode:
            # Refresh go-to-sleep alarm
            if sleep_alarm_id == "":
                sleep_alarm_id = alarm_handler_.set_up_alarm(datetime.now() + timedelta(seconds=INACTIVITY_TIMEOUT_SECS), AlarmCyclic.NO, AlarmAction.GO_TO_SLEEP_ALARM, "", False)
            else:
                alarm_handler_.update_alarm(sleep_alarm_id, timestamp=datetime.now() + timedelta(seconds=INACTIVITY_TIMEOUT_SECS))
    

    else:
        ###################################################################################################################
        # No voice event, process time events

        alarm = alarm_handler_.is_alarm_triggered()
        if alarm:
            if alarm.action == AlarmAction.GO_TO_SLEEP_ALARM:
                log_.printst(f"No voice detected for {INACTIVITY_TIMEOUT_SECS} secs.")
                sleep_alarm_id = "" # Alarm already fired and deleted by alarm_handler
                if first_ever_wup:
                    log_.printst("Going to sleep mode.")
                    wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.BYE)
                    timetostart,timetoend = animationhandler_.request_animation(Scene.OUTRO, Character.BLINKY, TriggerAnimationChange.SMOOTH_TRANSITION)
                    time.sleep(timetostart) # To align start of animation with start of sound
                    audio_.play_wav(wavpath)
                    sleep_mode = True # Set the holo-device in sleep mode
                    if hologram_available:
                        time.sleep(timetoend-timetostart-0.2) # Wait here for animation to stop, instead of creating a complex timers logic, just 
                                                                # (-0.2 used to power off hologram before animation ends and device plays next one)
                        hologram_.turn_off()
                continue
            elif alarm.action == AlarmAction.USER_ALARM:
                log_.printst(f"Alarm event triggered.")
                if sleep_mode:
                    if hologram_available:
                        hologram_.turn_on()
                        time.sleep(2)
                    sleep_mode = False

                # First: Reproduce clock alarm animation and sound
                wavpath = get_fixed_audio_response_path(audio_.get_input_device_sample_rate(), Fixed_Audio_Response.ALARM)
                audio_.play_wav(wavpath)
                timetostart,timetoend = animationhandler_.request_animation(Scene.ALARM, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)
                time.sleep(timetoend)

                # Then, reproduce blinky animation and sound explaining the alarm if info is available
                if alarm.wav != "":
                    wavpath = alarm.wav
                    duration = audio_.get_wav_duration(wavpath)
                    audio_.play_wav(wavpath)
                    timetostart,timetoend = animationhandler_.request_animation(Scene.TIME, Character.BLINKY, TriggerAnimationChange.IMMEDIATELY, duration)

                    # Trigger a task after 'duration' seconds to remove the wav
                    if alarm.wav and alarm.cyclic == AlarmCyclic.NO:
                        timer = threading.Timer(duration+5, lambda path=wavpath: os.remove(path)) # Fire and Forget. Not that critical if error.
                        timer.start()
                
                # Refresh go-to-sleep alarm
                if sleep_alarm_id == "":
                    sleep_alarm_id = alarm_handler_.set_up_alarm(datetime.now() + timedelta(seconds=INACTIVITY_TIMEOUT_SECS), AlarmCyclic.NO, AlarmAction.GO_TO_SLEEP_ALARM, "", False)
                else:
                    alarm_handler_.update_alarm(sleep_alarm_id, timestamp=datetime.now() + timedelta(seconds=INACTIVITY_TIMEOUT_SECS))

        else:
            # No voice event, no time events, continue monitoring voice
            pass
