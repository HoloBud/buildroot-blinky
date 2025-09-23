import datetime
import enum
import json
import collections
import os
from typing import Optional, List, Dict, Any
import uuid # To generate unique IDs for alarms
from log import LogModule


# --- Enums for alarm actions and cycles ---
class AlarmAction(enum.Enum):
    """Actions to perform when an alarm triggers."""
    USER_ALARM = "user_alarm"
    GO_TO_SLEEP_ALARM = "go_to_sleep_alarm"
    WAKE_UP_ALARM = "wake_up_alarm"

class AlarmCyclic(enum.Enum):
    """Types of repetition for cyclic alarms."""
    NO = "no"
    DAILY = "daily"
    WEEKLY = "weekly"
    WEEKDAY = "weekday" # Monday to Friday
    EVERY_MONDAY = "every_monday"
    EVERY_TUESDAY = "every_tuesday"
    EVERY_WEDNESDAY = "every_wednesday"
    EVERY_THURSDAY = "every_thursday"
    EVERY_FRIDAY = "every_friday"
    EVERY_SATURDAY = "every_saturday"
    EVERY_SUNDAY = "every_sunday"

# --- Class to represent an alarm object ---
class AlarmObject:
    def __init__(self,
                 timestamp: datetime.datetime,
                 action: AlarmAction,
                 speech: str,
                 cyclic: AlarmCyclic = AlarmCyclic.NO,
                 alarm_id: Optional[str] = None,
                 persists: bool = True,
                 wav: str = ""):
        self.timestamp = timestamp
        self.action = action
        self.speech = speech
        self.cyclic = cyclic
        self.id = alarm_id if alarm_id is not None else str(uuid.uuid4())
        self.persists = persists
        self.wav = wav

    def __lt__(self, other):
        """Allows sorting AlarmObjects by timestamp."""
        return self.timestamp.timestamp() < other.timestamp.timestamp()

    def to_dict(self) -> Dict[str, Any]:
        """Converts the alarm object to a dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(), # ISO format for easy serialization
            "action": self.action.value,
            "speech": self.speech,
            "cyclic": self.cyclic.value,
            "persists": self.persists,
            "wav": self.wav
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """Creates an alarm object from a dictionary (useful for JSON deserialization)."""
        # Ensure 'persists' and 'wav' have default values if not present in older data
        return cls(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            action=AlarmAction(data["action"]),
            speech=data["speech"],
            cyclic=AlarmCyclic(data["cyclic"]),
            alarm_id=data["id"],
            persists=data.get("persists", True), # Read 'persists' or use True by default
            wav=data.get("wav", "") # Read 'wav' or use empty string by default
        )

# --- Main AlarmHandler Class ---
class AlarmHandler:
    def __init__(self, backup_filepath: str = "alarms_backup.json", log_module: Optional[LogModule] = None):
        self._alarms: List[AlarmObject] = []
        self.backup_filepath = backup_filepath
        self.log_ = log_module if log_module else LogModule()
        self._initialized = False

    def initialize(self):
        """
        Loads pending alarms from the backup file.
        Must be called once at the application startup.
        """
        if self._initialized:
            self.log_.printst("AlarmHandler already initialized. Ignoring duplicate call.")
            return

        self.log_.printst(f"Initializing AlarmHandler. Loading alarms from {self.backup_filepath}...")
        try:
            with open(self.backup_filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._alarms = [AlarmObject.from_dict(item) for item in data]
                # Ensure the list is sorted after loading
                self._alarms.sort()
            self.log_.printst(f"Loaded {len(self._alarms)} alarms from backup.")
        except FileNotFoundError:
            self.log_.printst("Alarm backup file not found. Starting with empty list.")
        except json.JSONDecodeError as e:
            self.log_.printst(f"Error decoding JSON from backup file: {e}. Starting with empty list.")
            self._alarms = [] # Reset if there's a JSON error
        except Exception as e:
            self.log_.printst(f"Unexpected error loading alarms: {e}. Starting with empty list.")
            self._alarms = []
        
        self._initialized = True
        self._save_alarms() # Save in case the list was reset or sorted

    def _save_alarms(self):
        """Saves the current state of alarms to the backup file."""
        if not self._initialized:
            self.log_.printst("Warning: Attempting to save alarms before initialization.")
            return

        try:
            # Convert AlarmObject to dicts for serialization, filtering by 'persists'
            data_to_save = [alarm.to_dict() for alarm in self._alarms if alarm.persists]
            with open(self.backup_filepath, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4)
            # self.log_.printst(f"Alarms saved to {self.backup_filepath}.") # Optional: to avoid too much log
        except Exception as e:
            self.log_.printst(f"Error saving alarms to {self.backup_filepath}: {e}")

    def set_up_alarm(self,
                     timestamp: datetime.datetime,
                     cyclic: AlarmCyclic,
                     action: AlarmAction,
                     speech: str,
                     persists: bool = True,
                     wav: str = ""):
        """
        Sets up a new alarm.
        timestamp: datetime.datetime - The exact time the alarm should first sound.
        cyclic: AlarmCyclic - If and how the alarm repeats.
        action: AlarmAction - The type of action to execute.
        speech: str - What should be said when the alarm triggers.
        persists: bool - If True, the alarm will be saved to the backup file and persist across resets.
        wav: str - Optional path to a WAV file to be played when the alarm triggers.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return

        new_alarm = AlarmObject(timestamp=timestamp, action=action, speech=speech, cyclic=cyclic, persists=persists, wav=wav)
        
        # Insert the alarm while maintaining order
        # Although a simple list and sort() is sufficient for small/medium lists
        # For very large lists, using heapq or a tree structure would be more efficient.
        # For this case, keeping the list sorted is simple and efficient with typical alarm numbers.
        self._alarms.append(new_alarm)
        self._alarms.sort() # Re-sort after adding
        self._save_alarms()
        self.log_.printst(f"Alarm configured: ID={new_alarm.id}, Time={new_alarm.timestamp}, Cyclic={new_alarm.cyclic.value}, Persists={new_alarm.persists}, WAV='{new_alarm.wav}'")

        return new_alarm.id

    def clear_all_alarms(self, only_user_alarms: bool = False):
        """
        Clears configured alarms.
        only_user_alarms: bool - If True, only alarms with the action USER_ALARM will be cleared.
                                If False (default), all alarms will be cleared.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return

        if only_user_alarms:
            initial_count = len(self._alarms)
            self._alarms = [alarm for alarm in self._alarms if alarm.action != AlarmAction.USER_ALARM]
            cleared_count = initial_count - len(self._alarms)
            self.log_.printst(f"{cleared_count} user alarms have been cleared.")
        else:
            self._alarms = []
            self.log_.printst("All alarms have been cleared.")

        self._save_alarms()


    def get_alarm_obj(self, alarm_id: str) -> Optional[AlarmObject]:
        """
        Retrieves an AlarmObject by its ID.
        Returns the AlarmObject if found, otherwise None.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return None

        for alarm in self._alarms:
            if alarm.id == alarm_id:
                return alarm
        self.log_.printst(f"Alarm with ID {alarm_id} not found.")
        return None

    def update_alarm(self, alarm_id: str, **kwargs) -> bool:
        """
        Updates an existing alarm.
        alarm_id: str - The ID of the alarm to update.
        kwargs: keyword arguments corresponding to AlarmObject attributes (e.g., timestamp, speech, wav).
        Returns True if the alarm was updated successfully, False otherwise.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return False

        alarm_found = False
        requires_sort = False
        requires_save = False

        for i, alarm in enumerate(self._alarms):
            if alarm.id == alarm_id:
                alarm_found = True
                for key, value in kwargs.items():
                    if hasattr(alarm, key):
                        if key == "timestamp":
                            if not isinstance(value, datetime.datetime):
                                self.log_.printst(f"Error: 'timestamp' must be a datetime object. Received {type(value)}.")
                                return False
                            alarm.timestamp = value
                            requires_sort = True
                            requires_save = True
                        elif key == "action":
                            if not isinstance(value, AlarmAction):
                                self.log_.printst(f"Error: 'action' must be an AlarmAction enum. Received {type(value)}.")
                                return False
                            alarm.action = value
                            requires_save = True
                        elif key == "speech":
                            alarm.speech = str(value)
                            requires_save = True
                        elif key == "cyclic":
                            if not isinstance(value, AlarmCyclic):
                                self.log_.printst(f"Error: 'cyclic' must be an AlarmCyclic enum. Received {type(value)}.")
                                return False
                            alarm.cyclic = value
                            requires_sort = True # Cyclic change might affect sorting if logic for cyclic alarms changed to always be in future
                            requires_save = True
                        elif key == "persists":
                            if not isinstance(value, bool):
                                self.log_.printst(f"Error: 'persists' must be a boolean. Received {type(value)}.")
                                return False
                            alarm.persists = value
                            requires_save = True
                        elif key == "wav":
                            alarm.wav = str(value)
                            requires_save = True
                        else:
                            self.log_.printst(f"Warning: Attempted to update unknown attribute '{key}' for alarm {alarm_id}.")
                    else:
                        self.log_.printst(f"Warning: AlarmObject does not have attribute '{key}'.")
                break
        
        if alarm_found:
            if requires_sort:
                self._alarms.sort()
            if requires_save: # Only save if a significant change occurred
                self._save_alarms()
            self.log_.printst(f"Alarm {alarm_id} updated successfully.")
            return True
        else:
            self.log_.printst(f"Alarm with ID {alarm_id} not found for update.")
            return False

    def delete_alarm(self, alarm_id: str) -> bool:
        """
        Deletes an alarm by its ID.
        alarm_id: str - The ID of the alarm to delete.
        Returns True if the alarm was found and deleted, False otherwise.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return False

        initial_alarm_count = len(self._alarms)
        # Recreate the list, excluding the alarm with the matching ID
        self._alarms = [alarm for alarm in self._alarms if alarm.id != alarm_id]
        
        if len(self._alarms) < initial_alarm_count:
            # If the list is now shorter, an alarm was deleted
            self._save_alarms()
            self.log_.printst(f"Alarm with ID {alarm_id} has been deleted.")
            return True
        else:
            # If the list length is the same, no alarm was found
            self.log_.printst(f"Alarm with ID {alarm_id} not found for deletion.")
            return False

    def is_alarm_triggered(self) -> Optional[AlarmObject]:
        """
        Checks if any alarm should trigger.
        Returns the triggered AlarmObject or None if no alarms are pending or none have triggered.
        Manages the repetition of cyclic alarms.
        """
        if not self._initialized:
            self.log_.printst("Error: AlarmHandler not initialized. Call initialize() first.")
            return None
        if not self._alarms:
            return None # No alarms configured

        # Since the list is sorted by timestamp, we only need to look at the first element.
        now = datetime.datetime.now()
        next_alarm = self._alarms[0]

        if next_alarm.timestamp.timestamp() <= now.timestamp():
            # The alarm should trigger
            triggered_alarm = self._alarms.pop(0) # Remove the triggering alarm
            self.log_.printst(f"Alarm triggered: ID={triggered_alarm.id}, Time={triggered_alarm.timestamp}, Action={triggered_alarm.action.value}, WAV='{triggered_alarm.wav}'")

            if triggered_alarm.cyclic != AlarmCyclic.NO:
                # Recalculate the next timestamp for cyclic alarms
                next_timestamp = self._recalculate_next_timestamp(triggered_alarm)
                if next_timestamp:
                    # Create a new instance for the next occurrence
                    recurring_alarm = AlarmObject(
                        timestamp=next_timestamp,
                        action=triggered_alarm.action,
                        speech=triggered_alarm.speech,
                        cyclic=triggered_alarm.cyclic,
                        alarm_id=triggered_alarm.id, # Keep the same ID for recurrence
                        persists=triggered_alarm.persists,
                        wav=triggered_alarm.wav
                    )
                    self._alarms.append(recurring_alarm)
                    self._alarms.sort() # Re-sort to maintain efficiency
                    self.log_.printst(f"Recalculated cyclic alarm {triggered_alarm.id} for {next_timestamp}.")
                else:
                    self.log_.printst(f"Warning: Could not recalculate next timestamp for cyclic alarm {triggered_alarm.id}.")
            
            self._save_alarms() # Save the updated alarm state
            return triggered_alarm
        else:
            return None # The next alarm is not yet due

    def _recalculate_next_timestamp(self, alarm: AlarmObject) -> Optional[datetime.datetime]:
        """
        Calculates the next timestamp for a cyclic alarm, ensuring it's in the future.
        """
        current_dt = alarm.timestamp
        now = datetime.datetime.now()
        
        # If the alarm should have already sounded multiple times (e.g., initialize() with past alarms)
        # Ensure that the next occurrence is ALWAYS in the future.
        # Adjust current_dt so that it is the nearest future occurrence
        # while maintaining the original time.
        while current_dt <= now:
            if alarm.cyclic == AlarmCyclic.DAILY:
                current_dt += datetime.timedelta(days=1)
            elif alarm.cyclic == AlarmCyclic.WEEKLY:
                current_dt += datetime.timedelta(weeks=1)
            elif alarm.cyclic == AlarmCyclic.WEEKDAY:
                current_dt += datetime.timedelta(days=1)
                # Skip weekends
                while current_dt.weekday() >= 5: # 5 is Saturday, 6 is Sunday
                    current_dt += datetime.timedelta(days=1)
            elif alarm.cyclic in [AlarmCyclic.EVERY_MONDAY, AlarmCyclic.EVERY_TUESDAY,
                                  AlarmCyclic.EVERY_WEDNESDAY, AlarmCyclic.EVERY_THURSDAY,
                                  AlarmCyclic.EVERY_FRIDAY, AlarmCyclic.EVERY_SATURDAY,
                                  AlarmCyclic.EVERY_SUNDAY]:
                target_weekday_map = {
                    AlarmCyclic.EVERY_MONDAY: 0,
                    AlarmCyclic.EVERY_TUESDAY: 1,
                    AlarmCyclic.EVERY_WEDNESDAY: 2,
                    AlarmCyclic.EVERY_THURSDAY: 3,
                    AlarmCyclic.EVERY_FRIDAY: 4,
                    AlarmCyclic.EVERY_SATURDAY: 5,
                    AlarmCyclic.EVERY_SUNDAY: 6,
                }
                target_weekday = target_weekday_map[alarm.cyclic]
                
                # Find the next target day of the week
                days_ahead = (target_weekday - current_dt.weekday() + 7) % 7
                if days_ahead == 0 and current_dt <= now: # If it's already today and the time has passed, go to next week
                    days_ahead = 7 
                
                current_dt += datetime.timedelta(days=days_ahead)
            else:
                self.log_.printst(f"Unknown cyclic type: {alarm.cyclic.value}")
                return None # Cannot recalculate
        
        return current_dt

# --- Example Usage and Simulation ---
if __name__ == "__main__":
    import time # Import time for the example sleep

    log_app = LogModule()
    # Clear the backup file before initializing for a clean simulation
    if os.path.exists("alarms_backup.json"):
        os.remove("alarms_backup.json")
        log_app.printst("Cleaned up alarms_backup.json for fresh start.")

    alarm_handler = AlarmHandler(log_module=log_app)
    
    # 1. Initialize the alarm handler (will load from file if it exists)
    alarm_handler.initialize()
    
    # 2. Set up some example alarms
    now = datetime.datetime.now()
    
    # Simple alarm in 10 seconds - persists (default)
    alarm_id_1 = alarm_handler.set_up_alarm(
        now + datetime.timedelta(seconds=10),
        AlarmCyclic.NO,
        AlarmAction.USER_ALARM,
        "It's time to take a break."
    )

    # Daily cyclic alarm (first occurrence in 20 seconds) - persists (default)
    alarm_id_2 = alarm_handler.set_up_alarm(
        now + datetime.timedelta(seconds=20),
        AlarmCyclic.DAILY,
        AlarmAction.GO_TO_SLEEP_ALARM,
        "Daily reminder to get ready for bed."
    )

    # Alarm that DOES NOT persist (will not be saved to file)
    alarm_id_no_persist = alarm_handler.set_up_alarm(
        now + datetime.timedelta(seconds=5), # Triggers very soon
        AlarmCyclic.NO,
        AlarmAction.USER_ALARM,
        "This alarm should NOT persist after a restart!",
        persists=False # Here's the new parameter!
    )

    # Cyclic alarm for next Monday at the same time (or the Monday of the next week if today's Monday already passed)
    # Set the time to 2 minutes in the future to ensure it doesn't trigger immediately
    next_monday = now + datetime.timedelta(days=(0 - now.weekday() + 7) % 7) # 0 for Monday
    next_monday_at_time = datetime.datetime(next_monday.year, next_monday.month, next_monday.day, now.hour, now.minute, now.second)
    if next_monday_at_time <= now: # If Monday already passed today, schedule for next Monday
        next_monday_at_time += datetime.timedelta(weeks=1)

    alarm_id_3 = alarm_handler.set_up_alarm(
        next_monday_at_time + datetime.timedelta(minutes=2), # Ensure it's in the future
        AlarmCyclic.EVERY_MONDAY,
        AlarmAction.WAKE_UP_ALARM,
        "It's Monday, get up, it's time for work!",
        persists=True # Explicitly persistent
    )


    log_app.printst("\n--- Testing get_alarm_obj and update_alarm ---")
    retrieved_alarm = alarm_handler.get_alarm_obj(alarm_id_1)
    if retrieved_alarm:
        log_app.printst(f"Retrieved Alarm 1: ID={retrieved_alarm.id}, Speech='{retrieved_alarm.speech}', Persists={retrieved_alarm.persists}")
        
        # Update the speech of alarm_id_1
        alarm_handler.update_alarm(alarm_id_1, speech="Time for a really important break!")
        updated_alarm = alarm_handler.get_alarm_obj(alarm_id_1)
        if updated_alarm:
            log_app.printst(f"Updated Alarm 1 Speech: '{updated_alarm.speech}'")

        # Try to update timestamp of alarm_id_2
        new_timestamp_for_alarm_2 = now + datetime.timedelta(seconds=5)
        log_app.printst(f"Attempting to update Alarm 2 timestamp to: {new_timestamp_for_alarm_2}")
        alarm_handler.update_alarm(alarm_id_2, timestamp=new_timestamp_for_alarm_2)
        updated_alarm_2 = alarm_handler.get_alarm_obj(alarm_id_2)
        if updated_alarm_2:
            log_app.printst(f"Updated Alarm 2 Timestamp: {updated_alarm_2.timestamp}")

    # Demonstrate that the 'no_persist' alarm exists in memory, but won't be saved
    retrieved_no_persist_alarm = alarm_handler.get_alarm_obj(alarm_id_no_persist)
    if retrieved_no_persist_alarm:
        log_app.printst(f"Retrieved No-Persist Alarm: ID={retrieved_no_persist_alarm.id}, Persists={retrieved_no_persist_alarm.persists}")


    log_app.printst("\n--- Testing delete_alarm ---")
    alarm_to_delete_id = alarm_handler.set_up_alarm(
        now + datetime.timedelta(seconds=45),
        AlarmCyclic.NO,
        AlarmAction.USER_ALARM,
        "This alarm will be deleted before it triggers."
    )
    log_app.printst(f"Created an alarm to be deleted, ID: {alarm_to_delete_id}")
    
    # Delete the alarm
    delete_success = alarm_handler.delete_alarm(alarm_to_delete_id)
    if delete_success:
        log_app.printst(f"Successfully called delete_alarm for ID: {alarm_to_delete_id}")
    
    # Verify it's gone
    retrieved_deleted_alarm = alarm_handler.get_alarm_obj(alarm_to_delete_id)
    if not retrieved_deleted_alarm:
        log_app.printst(f"Verification successful: Alarm with ID {alarm_to_delete_id} was not found after deletion.")
    else:
        log_app.printst(f"Verification FAILED: Alarm with ID {alarm_to_delete_id} was found after deletion.")

    log_app.printst("\nStarting main application loop. Polling AlarmHandler every 0.5 seconds.")
    
    # 3. Simulate your application's main loop polling is_alarm_triggered()
    polling_interval = 0.5 # 500 ms
    start_time = time.time()

    try:
        while True:
            triggered_alarm = alarm_handler.is_alarm_triggered()
            if triggered_alarm:
                log_app.printst(f"--- ALARM RECEIVED --- ID: {triggered_alarm.id}, ACTION: {triggered_alarm.action.name}, MESSAGE: '{triggered_alarm.speech}'")
                # Here would be the logic to play the speech or execute the action

            # Small pause to simulate the polling interval
            time.sleep(polling_interval)
            
            # Exit condition for the example
            if time.time() - start_time > 60: # Run for 60 seconds
                log_app.printst("Simulation finished after 60 seconds.")
                break

    except KeyboardInterrupt:
        log_app.printst("Simulation interrupted by user.")
    finally:
        log_app.printst("Application shutting down.")
        # Optional: alarm_handler._save_alarms() could be called here as well
        # to ensure any last-minute changes are saved, although
        # it's already saved with each set_up_alarm and is_alarm_triggered.

    log_app.printst("\n--- Simulating Application Restart ---")
    # To demonstrate persistence, we create a new AlarmHandler instance
    # This will simulate an application restart.
    log_app.printst("Creating a new AlarmHandler instance to simulate restart...")
    new_alarm_handler = AlarmHandler(log_module=log_app)
    new_alarm_handler.initialize() # This will only load persistent alarms

    log_app.printst(f"Alarms loaded after restart: {len(new_alarm_handler._alarms)}")
    for alarm in new_alarm_handler._alarms:
        log_app.printst(f"  - Loaded Alarm ID: {alarm.id}, Time: {alarm.timestamp}, Persists: {alarm.persists}")
    
    # Try to find the alarm that was NOT persistent
    restarted_no_persist_alarm = new_alarm_handler.get_alarm_obj(alarm_id_no_persist)
    if not restarted_no_persist_alarm:
        log_app.printst(f"As expected, alarm with ID {alarm_id_no_persist} (non-persisting) was NOT loaded after restart.")
    else:
        log_app.printst(f"Unexpected: Non-persisting alarm with ID {alarm_id_no_persist} was found after restart.")
