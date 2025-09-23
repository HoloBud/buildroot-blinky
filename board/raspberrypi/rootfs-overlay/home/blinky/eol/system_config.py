import sounddevice as sd
import configparser
import os
import uuid
from dataclasses import dataclass, field
from hologram_fans import FanModel

CONFIG_FILE = "system.cfg"

# --- Dataclasses for Configuration Structure ---
@dataclass(frozen=True)
class AudioConfig:
    input_device_index: int
    input_device_name: str
    output_device_index: int
    output_device_name: str

@dataclass(frozen=True)
class HardwareConfig:
    hologram_fan_type: FanModel

@dataclass(frozen=True)
class ProvisioningConfig:
    uuid: str
    school_name: str

@dataclass(frozen=True)
class InteractionConfig:
    initial_behavior: int
    register_hw: int

@dataclass(frozen=True)
class SystemConfig:
    audio: AudioConfig = field(default_factory=lambda: AudioConfig(None, "Default System Input", None, "Default System Output"))
    hardware: HardwareConfig = field(default_factory=lambda: HardwareConfig(FanModel.UHD_47CM))
    provision: ProvisioningConfig = field(default_factory=lambda: ProvisioningConfig("", ""))
    interaction: InteractionConfig = field(default_factory=lambda: InteractionConfig(False, True))

# --- Helper functions ---
def get_default_devices():
    """
    Gets the default input and output device indices as configured in the system.
    Returns (default_input_idx, default_output_idx).
    """
    try:
        default_input, default_output = sd.default.device
        return default_input, default_output
    except Exception:
        return None, None

def get_input_devices():
    """Returns a list of available input devices."""
    devices = sd.query_devices()
    input_devices = []
    for i, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            input_devices.append({
                'index': i,
                'name': device['name'],
                'channels': device['max_input_channels'],
                'samplerate': device['default_samplerate']
            })
    return input_devices

def get_output_devices():
    """Returns a list of available output devices."""
    devices = sd.query_devices()
    output_devices = []
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            output_devices.append({
                'index': i,
                'name': device['name'],
                'channels': device['max_output_channels'],
                'samplerate': device['default_samplerate']
            })
    return output_devices

def display_and_select_device(device_list, device_type_name, default_global_index, selected_global_index):
    """
    Displays a filtered list of devices, indicating the default one and the previously selected one,
    and prompts the user for selection.
    Returns the index and name of the selected device.
    """
    if not device_list:
        print(f"\n--- No {device_type_name} devices found. ---")
        return None, None

    print(f"\n--- Select a {device_type_name} device ---")
    for i, device in enumerate(device_list):
        tags = []
        if device['index'] == default_global_index:
            tags.append("DEFAULT")
        if device['index'] == selected_global_index:
            tags.append("SELECTED")
        
        tag_str = " (" + ", ".join(tags) + ")" if tags else ""
        
        print(f"[{i}] {device['name']} (Channels: {device['channels']}, Sample Rate: {int(device['samplerate'])} Hz, Global ID: {device['index']}){tag_str}")
    
    valid_selection = False
    selected_internal_index = -1
    
    while not valid_selection:
        try:
            choice = input(f"Enter the number for the {device_type_name} device you want to use: ")
            selected_internal_index = int(choice)
            
            if 0 <= selected_internal_index < len(device_list):
                valid_selection = True
            else:
                print("Invalid device number. Please enter a number from the list.")
        except ValueError:
            print("Invalid input. Please enter a number.")
    
    selected_device_info = device_list[selected_internal_index]
    return selected_device_info['index'], selected_device_info['name']

def select_hologram_fan_type(current_fan_model: FanModel = None):
    """
    Prompts the user to select a hologram fan type, indicating the currently selected one.
    Returns the selected string value.
    """
    fan_options = [model.value for model in FanModel] #
    
    print("\n--- Select Hologram Fan Type ---")
    for i, option_value in enumerate(fan_options):
        is_selected_tag = " (SELECTED)" if current_fan_model and option_value == current_fan_model.value else ""
        print(f"[{i}] {option_value}{is_selected_tag}")
    
    valid_selection = False
    selected_fan_type_str = ""
    
    while not valid_selection:
        try:
            choice = input("Enter the number for the Hologram Fan Type: ")
            selected_internal_index = int(choice)
            
            if 0 <= selected_internal_index < len(fan_options):
                selected_fan_type_str = fan_options[selected_internal_index]
                valid_selection = True
            else:
                print("Invalid number. Please enter a number from the list.")
        except ValueError:
            print("Invalid input. Please enter a number.")
            
    return selected_fan_type_str

def save_config_file(input_index, input_name, output_index, output_name, hologram_fan_type_str, dev_uuid, school_name, run_interactive_behavior, register_hw):
    """Saves the selected device and fan information to system.cfg."""
    config = configparser.ConfigParser()
    
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        print(f"\n'{CONFIG_FILE}' exists. Updating configuration.")
    else:
        print(f"\n'{CONFIG_FILE}' does not exist. Creating new configuration.")

    config['Audio'] = {
        'input_device_index': str(input_index),
        'input_device_name': input_name,
        'output_device_index': str(output_index),
        'output_device_name': output_name
    }
    
    config['Hardware'] = {
        'hologram_fan_type': hologram_fan_type_str
    }

    if len(dev_uuid) != 0 and len(school_name) != 0:
        config['Provisioning'] = {
            'uuid': dev_uuid,
            'school': school_name
        }
    
    config['Interaction'] = {
        'initial_behavior': str(run_interactive_behavior),
        'register_hw': str(register_hw)
    }

    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)
    print(f"\nConfiguration saved to '{CONFIG_FILE}'.")


# --- load_and_apply_config returns SystemConfig object ---
def load_and_apply_config() -> SystemConfig:
    """
    Loads configuration from system.cfg and returns a SystemConfig object.
    Also attempts to set sounddevice default devices if audio config is found.
    """
    config = configparser.ConfigParser()
    audio_cfg = None
    hardware_cfg = None
    provisioning_cfg = None
    interaction_cfg = None

    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
        print(f"[{__name__}] Loading configuration from '{CONFIG_FILE}'...")

        # Load Audio Configuration
        if 'Audio' in config:
            try:
                input_index = int(config['Audio']['input_device_index'])
                input_name = config['Audio']['input_device_name']
                output_index = int(config['Audio']['output_device_index'])
                output_name = config['Audio']['output_device_name']
                audio_cfg = AudioConfig(input_index, input_name, output_index, output_name)

                # Set sounddevice default devices
                try:
                    sd.default.device = (input_index, output_index)
                    print(f"[{__name__}] Sounddevice default devices set to: "
                          f"Input: [{input_index}] {input_name}, "
                          f"Output: [{output_index}] {output_name}")
                except sd.PortAudioError as e:
                    print(f"[{__name__}] WARNING: Could not set sounddevice default devices "
                          f"[{input_index}, {output_index}]. "
                          f"Error: {e}. They might be unavailable or already in use. "
                          f"Application will attempt to use them when explicitly passed.")
                except Exception as e:
                     print(f"[{__name__}] WARNING: Error setting sounddevice default devices: {e}")

            except (ValueError, KeyError) as e:
                print(f"[{__name__}] WARNING: Incomplete or invalid Audio section in '{CONFIG_FILE}'. "
                      f"Using default audio configuration. Error: {e}")
        else:
            print(f"[{__name__}] Section 'Audio' not found in '{CONFIG_FILE}'. Using default audio configuration.")

        # Load Hardware Configuration
        if 'Hardware' in config:
            try:
                hologram_fan_type_str = config['Hardware']['hologram_fan_type']
                hardware_cfg = HardwareConfig(FanModel(hologram_fan_type_str))
                print(f"[{__name__}] Hologram Fan Type loaded: {hardware_cfg.hologram_fan_type.value}")
            except KeyError as e:
                print(f"[{__name__}] WARNING: 'hologram_fan_type' not found in 'Hardware' section. Using default hardware configuration. Error: {e}")
            except ValueError as e:
                print(f"[{__name__}] WARNING: Invalid 'hologram_fan_type' value '{hologram_fan_type_str}' in config. Using default hardware configuration. Error: {e}")
        else:
            print(f"[{__name__}] Section 'Hardware' not found in '{CONFIG_FILE}'. Using default hardware configuration.")

        if 'Provisioning' in config:
            uuid = config['Provisioning']['uuid']
            school = config['Provisioning']['school']
            provisioning_cfg = ProvisioningConfig(uuid, school)
        
        if 'Interaction' in config:
            initial_behavior = config['Interaction']['initial_behavior']
            register_hw = config['Interaction']['register_hw']
            interaction_cfg = InteractionConfig(initial_behavior, register_hw)

    else:
        print(f"[{__name__}] '{CONFIG_FILE}' does not exist. Using default system configuration.")

    # Return the loaded or default configuration
    return SystemConfig(audio=audio_cfg, hardware=hardware_cfg, provision=provisioning_cfg, interaction=interaction_cfg)


# --- Main function to run the configurator script directly ---
def main():
    print("This script will help you configure audio and hardware devices for your application.")
    
    # Attempt to load existing configuration for display purposes
    current_config = load_and_apply_config() 

    # Get system's default devices for user guidance
    default_input_global_index, default_output_global_index = get_default_devices()
    
    # Extract currently selected indices for display
    selected_input_global_index = current_config.audio.input_device_index if current_config.audio else None
    selected_output_global_index = current_config.audio.output_device_index if current_config.audio else None
    
    # 1. Get and list only input devices (microphones)
    input_devices = get_input_devices()
    if not input_devices:
        print("No input devices (microphones) found. Ensure they are connected and recognized.")
        return

    # 2. Select microphone (input)
    selected_input_index, selected_input_name = display_and_select_device(
        input_devices, "input (microphone)", default_input_global_index, selected_input_global_index
    )
    if selected_input_index is None:
        print("Could not select an input device. Aborting configuration.")
        return

    # 3. Get and list only output devices
    output_devices = get_output_devices()
    if not output_devices:
        print("No output devices found. Ensure they are connected and recognized.")
        return

    # 4. Select audio output
    selected_output_index, selected_output_name = display_and_select_device(
        output_devices, "audio output", default_output_global_index, selected_output_global_index
    )
    if selected_output_index is None:
        print("Could not select an output device. Aborting configuration.")
        return

    # 5. Select Hologram Fan Type
    selected_hologram_fan_type_str = select_hologram_fan_type(current_config.hardware.hologram_fan_type if current_config.hardware else None)

    # 6. Generate UUID if the entry does not exist in the cfg file
    found_uuid_entry = False
    dev_uuid = ""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as cfg_file:
            for line in cfg_file:
                if "uuid" in line:
                    found_uuid_entry = True
                    break

    if not found_uuid_entry:
        dev_uuid = str(uuid.uuid4())
        print(f'Generated UUID: {dev_uuid}\n')
    else:
        print("\nThis device has a UUID assigned. Cannot change it here to avoid DB inconsistencies.")

    # 7. Register school name if the entry exists in the cfg file, ask user to overwrite
    found_school_entry = False
    school_name = ""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as cfg_file:
            for line in cfg_file:
                if "school" in line:
                    found_school_entry = True
                    break

    if not found_school_entry:
        school_name = input("Write school name:")
    else:
        print("\nThis device is assigned to a school already. Cannot change it here to avoid DB inconsistencies.")

    # Disable the interaction between blinky and the user (demo purposes)
    run_interactive_behavior = 0
    # Register HW in DB
    register_hw = 1

    # 8. Save configuration to file (using the new saving function)
    save_config_file(selected_input_index, selected_input_name, selected_output_index, selected_output_name, selected_hologram_fan_type_str, dev_uuid, school_name, run_interactive_behavior, register_hw)

    print("\nConfiguration completed!")

if __name__ == "__main__":
    main()
