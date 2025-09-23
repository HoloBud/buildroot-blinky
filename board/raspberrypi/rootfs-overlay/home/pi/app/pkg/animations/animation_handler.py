import random
import threading
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Dict, Any
from .animations_table import ANIMATIONS_TABLE


class Character(Enum):
    BLINKY = "blinky"


class Scene(Enum):
    ALARM = "alarm"
    HAPPY = "happy"
    IDLE = "idle"
    INTRO = "intro"
    LISTENING = "listen"
    OUTRO = "outro"
    PII = "pii"
    SEARCHING = "search"
    SPEAKING = "speak"
    TIME = "time"

class TriggerAnimationChange(Enum):
    IMMEDIATELY = 0             # Change animation immediately
    TRY_SMOOTH_TRANSITION = 1   # Try to do a smooth transition but with a maximum waiting time, otherwise, change immediately
    SMOOTH_TRANSITION = 2       # Wait for a smooth transition point (could wait until the end if transition not found)
    AFTER_CURRENT = 3           # Wait until current animation finishes


class AnimationHandler:
    IDLE_MODE_COUNT_BEFORE_IDLE = 10 # Amount of LISTENING animations before IDLE animation is played during IDLE MODE
    def __init__(self, play_animation: Callable[[Dict[str, Any], bool], None], verbose: bool = False, animation_table: Optional[Any] = None, timer_factory: Optional[Callable[..., threading.Timer]] = None, get_timestamp_fn: Optional[Callable[[], float]] = None):
        """
        Initializes the AnimationHandler.
        Args:
            play_animation: A function that accepts (animation_entry: dict, loop_play: bool)
            verbose: If True, prints detailed logs.
            animation_table: The table containing animation data. Defaults to ANIMATIONS_TABLE.
            timer_factory: A factory function for creating timers (e.g., threading.Timer). For testing.
            get_timestamp_fn: A function that returns the current timestamp. For testing.
        """
        self.play_animation = play_animation
        self.verbose = verbose

        self.thread_variables_lock = threading.Lock()
        self.current_animation: Optional[Dict[str, Any]] = None
        self.current_animation_duration: float = 0.0 # Duration of the currently playing animation
        self.current_animation_start_timestamp: float = 0.0 # Start timestamp of the currently playing animation

        self.next_animation: Optional[Dict[str, Any]] = None
        self.next_animation_duration: float = 0.0 # Adjusted duration for the next animation to play
        self.next_animation_timer: Optional[threading.Timer] = None # The scheduled timer for the next transition
        self.next_animation_idle_mode: bool = True # Indicates if an IDLE animation should be scheduled afterwards
        self.next_animation_idle_mode_countdown_for_idle = AnimationHandler.IDLE_MODE_COUNT_BEFORE_IDLE

        self.animation_table = animation_table if animation_table is not None else ANIMATIONS_TABLE
        self.timer_factory = timer_factory if timer_factory is not None else threading.Timer
        self.get_timestamp_fn = get_timestamp_fn if get_timestamp_fn is not None else lambda: datetime.now().timestamp()


    def request_animation(self, scene: Scene, character: Character, trigger_change: TriggerAnimationChange, requested_duration: float = 0):
        """
        Requests an animation change.
        Args:
            scene: The target scene for the animation.
            character: The character for the animation.
            trigger_change: The trigger type for the animation change.
            requested_duration: The desired duration for the animation (0 when we let the animation to finish).
        Returns:
            Tuple: time_to_start, time_to_end
            time_to_start: Relative time left for the requested animation to start
            time_to_end: Relative time left for the requested animation to finish its reproduction
        """

        # Filter animations matching the character and scene
        scene_candidates = [
            anim for anim in self.animation_table
            if anim["character"] == character.value and anim["scene"] == scene.value
        ]

        if not scene_candidates:
            print(f"[AnimationHandler] Err: No animations found for character '{character.value}' and scene '{scene.value}'")
            return # Exit if no candidates found

        candidate_selected = None
        next_animation_duration = 0.0

        if requested_duration == 0:
            # If no duration is requested, select a random animation
            candidate_selected = random.choice(scene_candidates)
            next_animation_duration = candidate_selected["duration"]
            if self.verbose:
                print(f"[AnimationHandler] Selected random animation {candidate_selected['file']} (duration {next_animation_duration:.2f}s) for requested_duration=0.")
        else:
            # Find the animation that best fits the requested duration
            best_diff = float('inf')
            found_any_candidate_combination = False # Flag to track if any valid combination was found
            
            for candidate in scene_candidates:
                # Include the full duration as a potential "smooth point"
                potential_smooth_points = sorted(list(set(candidate["smooth_transition_timestamps"] + [candidate["duration"]])))

                # Determine a reasonable range for number of repetitions to check
                # Go up to 2 full repetitions beyond what would minimally cover the requested duration
                # to catch cases where a slightly longer option is a much better fit
                max_repetitions_to_check = int(requested_duration / candidate["duration"]) + 2 
                if max_repetitions_to_check < 1: # Ensure we at least check 0 and 1 repetitions
                    max_repetitions_to_check = 1

                for n_repetitions in range(max_repetitions_to_check + 1): # Include 0 repetitions
                    for smooth_point in potential_smooth_points:
                        # Calculate the total duration for this combination
                        current_total_duration = n_repetitions * candidate["duration"] + smooth_point

                        if current_total_duration <= 0: # Ensure positive duration
                            continue

                        diff_from_target = abs(current_total_duration - requested_duration)

                        # Logic to update the best candidate found so far
                        # Always update if it's the very first valid combination found
                        if not found_any_candidate_combination:
                            best_diff = diff_from_target
                            candidate_selected = candidate
                            next_animation_duration = current_total_duration
                            found_any_candidate_combination = True
                        # If a better (smaller) difference is found
                        elif diff_from_target < best_diff:
                            best_diff = diff_from_target
                            candidate_selected = candidate
                            next_animation_duration = current_total_duration
                        # If the difference is equal, prefer a shorter total duration (for more deterministic tie-breaking)
                        elif diff_from_target == best_diff and current_total_duration < next_animation_duration:
                            best_diff = diff_from_target # Keep the same best_diff
                            candidate_selected = candidate
                            next_animation_duration = current_total_duration


                        # If an exact match is found, pick it immediately and stop searching
                        if best_diff == 0:
                            break # Exit inner (smooth_point) loop
                    if best_diff == 0:
                        break # Exit middle (n_repetitions) loop
                if best_diff == 0:
                    break # Exit outer (candidate) loop
            
            if candidate_selected is None: # Fallback if no suitable candidate was found after all attempts
                candidate_selected = random.choice(scene_candidates)
                next_animation_duration = candidate_selected["duration"]
                if self.verbose:
                    print(f"[AnimationHandler] Fallback: No suitable duration found, selected random animation {candidate_selected['file']}.")

            if self.verbose:
                print(f"[AnimationHandler] Selected animation {candidate_selected['file']} with adjusted duration {next_animation_duration:.2f}s for requested_duration={requested_duration:.2f}.")


        # Cancel any pending timer for the previous animation
        if self.next_animation_timer is not None and self.next_animation_timer.is_alive():
            self.next_animation_timer.cancel()

        # Update state with the next animation
        with self.thread_variables_lock:
            self.next_animation = candidate_selected
            self.next_animation_duration = next_animation_duration # The adjusted duration for this request
            # next_animation_idle_after is True by default in __init__
            # Only if the scene is OUTRO, disable automatic idle afterwards
            if scene == Scene.OUTRO:
                self.next_animation_idle_mode = False
            else:
                self.next_animation_idle_mode = True # Ensure it resets to True for other scenes


        # Determine the timer_value
        timer_value = 0.01 # Default value for IMMEDIATELY and as a fallback if cannot be calculated

        with self.thread_variables_lock: # Safely access self.current_animation
            current_animation = self.current_animation
            current_animation_start_timestamp = self.current_animation_start_timestamp
            current_animation_duration_actual = self.current_animation_duration # Actual duration of current playback

        if trigger_change == TriggerAnimationChange.AFTER_CURRENT:
            # Ensure there is a current animation to calculate remaining time
            if current_animation is not None:
                time_elapsed_current = self.get_timestamp_fn() - current_animation_start_timestamp
                # The timer is scheduled for the remaining time of the current animation. Minimum 0.01s.
                timer_value = max(0.01, current_animation_duration_actual - time_elapsed_current)
                if self.verbose:
                    print(f"[AnimationHandler] Scheduling AFTER_CURRENT in {timer_value:.2f} sec.")
            else:
                # If no current animation, act as IMMEDIATELY
                if self.verbose:
                    print(f"[AnimationHandler] No current animation for AFTER_CURRENT. Scheduling IMMEDIATELY (0.01s).")
                timer_value = 0.01

        elif trigger_change == TriggerAnimationChange.SMOOTH_TRANSITION:
            found_smooth_point = False
            if current_animation is not None:
                time_elapsed_current = self.get_timestamp_fn() - current_animation_start_timestamp
                
                if "smooth_transition_timestamps" in current_animation and current_animation["smooth_transition_timestamps"]:
                    for point in current_animation["smooth_transition_timestamps"]:
                        # Look for a transition point that is at least 0.01 seconds in the future
                        if (point - time_elapsed_current) > 0.01:
                            timer_value = (point - time_elapsed_current)
                            found_smooth_point = True
                            if self.verbose:
                                print(f"[AnimationHandler] Found smooth transition point on {point}. Scheduling in {timer_value:.2f} sec.")
                            break
            
            if not found_smooth_point:
                # If no smooth transition point found, or no current animation,
                # or animation has no transition points, fall back to AFTER_CURRENT (end of current animation).
                if current_animation is not None:
                    time_elapsed_current = self.get_timestamp_fn() - current_animation_start_timestamp
                    timer_value = max(0.01, current_animation_duration_actual - time_elapsed_current)
                    if self.verbose:
                        print(f"[AnimationHandler] Couldn't find smooth transition point. Playing after current in {timer_value:.2f} sec.")
                else:
                    # If no current animation, act as IMMEDIATELY
                    if self.verbose:
                        print(f"[AnimationHandler] No current animation for SMOOTH_TRANSITION. Scheduling IMMEDIATELY (0.01s).")
                    timer_value = 0.01
        
        elif trigger_change == TriggerAnimationChange.IMMEDIATELY:
            # Always schedule a very short timer so _change_animation runs in a new thread.
            if self.verbose:
                print(f"[AnimationHandler] Scheduling IMMEDIATELY (0.01s) for non-blocking execution.")
            timer_value = 0.01 # A small delay to allow asynchronous execution

        elif trigger_change == TriggerAnimationChange.TRY_SMOOTH_TRANSITION:
            # This logic is similar to SMOOTH_TRANSITION but should have a maximum waiting time.
            # Assuming for this example that if no smooth point is found within a short threshold, it acts as IMMEDIATELY.
            found_smooth_point = False
            if current_animation is not None:
                time_elapsed_current = self.get_timestamp_fn() - current_animation_start_timestamp
                
                if "smooth_transition_timestamps" in current_animation and current_animation["smooth_transition_timestamps"]:
                    for point in current_animation["smooth_transition_timestamps"]:
                        # Look for a transition point that is at least 0.01 seconds in the future
                        # A more complex "max waiting time" logic would go here.
                        if (point - time_elapsed_current) > 0.01:
                            timer_value = (point - time_elapsed_current)
                            found_smooth_point = True
                            if self.verbose:
                                print(f"[AnimationHandler] Found smooth transition point on {point}. Scheduling TRY_SMOOTH_TRANSITION in {timer_value:.2f} sec.")
                            break
            
            if not found_smooth_point:
                # If no smooth transition point found in time, or no current animation,
                # or animation has no transition points, fall back to IMMEDIATELY (0.01s)
                # to respect the "maximum waiting time" idea (i.e., don't wait long).
                if self.verbose:
                    print(f"[AnimationHandler] Couldn't find smooth transition point for TRY_SMOOTH_TRANSITION. Scheduling IMMEDIATELY (0.01s).")
                timer_value = 0.01

        # Schedule the timer for the next animation
        self.next_animation_timer = self.timer_factory(timer_value, self._change_animation)
        self.next_animation_timer.start()

        if self.verbose:
            print(f"{self.get_timestamp_fn()}: [AnimationHandler] Scheduled animation in {timer_value:.2f} sec: {candidate_selected['file']} (file_id={candidate_selected['file_id']}, duration={candidate_selected['duration']})")

        return timer_value, (timer_value + next_animation_duration)

    def get_current_animation(self) -> Optional[Dict[str, Any]]:
        """
        Safely retrieves the current animation.
        Returns: The current animation dictionary, or None.
        """
        with self.thread_variables_lock: # Ensure safe reading of current_animation
            return self.current_animation

    def _change_animation(self):
        """
        Sets the current animation and calls the play_animation callback.
        This method is meant to be called by the scheduled timer.
        """
        # Ensure next_animation is not None before using it
        if self.next_animation is None:
            if self.verbose:
                print(f"{self.get_timestamp_fn()}: [AnimationHandler] _change_animation called but next_animation is None. Skipping.")
            return

        # Acquire lock to safely update current_animation and its duration BEFORE playing.
        # These are pre-requisites for play_animation and represent what *will be* playing.
        with self.thread_variables_lock:
            # Copy next_animation to avoid race conditions if it changes before being fully processed
            next_animation_to_play = self.next_animation 
            self.current_animation = self.next_animation
            self.current_animation_duration = self.next_animation_duration
        
        # Call the external play_animation callback. This might be a blocking call to HW/UI.
        # Always loop=True to prevent our hologram switching to undesired animations
        self.play_animation(next_animation_to_play, loop_play=True) 
        
        with self.thread_variables_lock:
            self.current_animation_start_timestamp = self.get_timestamp_fn() # Update start timestamp here

        if self.verbose:
            print(f"{self.get_timestamp_fn()}: [AnimationHandler] Playing animation: {next_animation_to_play['file']} (file_id={next_animation_to_play['file_id']}, duration={next_animation_to_play['duration']})")

        ###########################
        # IDLE MODE
        #   If next_animation_idle_after is True, system will enter IDLE mode,
        #   which means to loop LISTENING animations and from time to time (configured in )
        #   an IDLE animation will be played.
        #   Ex:    5 times LISTENING -> 1 IDLE -> 5 times LISTENING -> 1 IDLE -> ...
        with self.thread_variables_lock:
            should_enter_idle_mode = self.next_animation_idle_mode and \
                                   self.current_animation is not None
            current_animation = self.current_animation
        
        if should_enter_idle_mode:
            if Scene(current_animation["scene"]) == Scene.LISTENING:
                self.next_animation_idle_mode_countdown_for_idle -= 1
            else:
                self.next_animation_idle_mode_countdown_for_idle = AnimationHandler.IDLE_MODE_COUNT_BEFORE_IDLE

            if self.next_animation_idle_mode_countdown_for_idle <= 0:
                self.request_animation(Scene.IDLE, Character.BLINKY, TriggerAnimationChange.AFTER_CURRENT)
            else:
                self.request_animation(Scene.LISTENING, Character.BLINKY, TriggerAnimationChange.AFTER_CURRENT)
