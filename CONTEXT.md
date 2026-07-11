# Pixel Pet Behavior

Terms describing how the desktop companion responds to user activity.

## Language

**Typing Activity**:
An ongoing burst of any physical keyboard presses that makes the pet perform its typing animation. Every key counts, including modifiers, function/media keys, and shortcuts; automatic repeats extend a held press rather than creating new steps.
_Avoid_: Keystroke reaction, typing event

**Typing Hold**:
The brief quiet interval after Typing Activity ends during which the pet keeps its ready-to-type pose unless another user action takes priority. Once interrupted, that hold is consumed and never resumes.
_Avoid_: Cooldown, typing delay

**Typing Step**:
One visible paw press caused by one physical keydown. Successive steps alternate left and right paws; a held key freezes its pressed pose until another key is pressed or all keys are released.
_Avoid_: Typing frame, key animation

**Stationary Placement**:
The normalized `x` and `y` position owned by Pet Behavior and returned by Behavior Snapshot. The pet remains at this user-chosen position during normal behavior. Walking or autonomous roaming is not part of the active behavior model; only explicit drag movement changes Stationary Placement. Companion Presentation converts between normalized placement and viewport coordinates, including sprite-aware clamping.
_Avoid_: Idle location, home position

**Petting Activity**:
Repeated left-right rubbing after the primary mouse button is pressed and held inside the Petting Region. The press origin selects the interaction: a Petting Region press arms Petting Activity, while a press on any remaining opaque body pixel begins the existing drag-and-drop interaction. That selection stays locked until the button is released, even when the pointer crosses between head and body. An armed head press causes no visual reaction until the first Petting Stroke reversal; releasing before that reversal ends silently with no Petting Pose, Petting Heart, or Petting Hold. The first valid reversal activates Petting Activity, shows the Petting Pose, and emits the first Petting Heart. While valid rubbing continues, Petting Hearts emit every 300 milliseconds independently of individual reversals, with at most three visible at once. Stroke movement counts only inside the Petting Region plus a small tolerance. Leaving that area or pausing the rubbing stops new hearts without changing the locked interaction; existing hearts finish vanishing, and returning resumes progress and emission. Active Petting Activity keeps the pet at its Stationary Placement.
_Avoid_: Click reaction, affection animation

**Petting Region**:
One normalized oval covering Catbone's head, shared across all nine Tracking Poses and scaled with the visible pet. A primary-button press inside this region selects Petting Activity; remaining opaque pixels select drag-and-drop.
_Avoid_: Head hitbox, petting mask

**Petting Stroke**:
A horizontal movement segment inside the Petting Region tolerance that spans at least 25% of the region's width before reversing direction. The reversal completes the stroke; shorter movement is pointer jitter and does not count.
_Avoid_: Swipe, rub event

**Petting Heart**:
A tiny, crisp pixel-art heart emitted during active Petting Activity. At 100% pet size it is approximately 5–7 screen pixels across, rises about 18 screen pixels with slight sideways drift over 900 milliseconds, and fades during the final third of that lifetime. Size and travel scale proportionally with the visible pet so the heart never overwhelms Catbone's head. When system animations are disabled, the stream becomes one static heart above the head throughout active petting and Petting Hold, then disappears without drifting or fading.
_Avoid_: Heart bubble, heart particle

**Petting Hold**:
The 600-millisecond interval after active Petting Activity ends when Catbone keeps the closed-eye pose without emitting new Petting Hearts. Existing hearts finish their lifetimes. Typing Activity, drag-and-drop, pause, or fullscreen hiding consumes the hold immediately; otherwise Tracking Pose resumes when it expires.
_Avoid_: Petting cooldown, affection delay

**Petting Reactions**:
A Live Setting, enabled by default, that permits Petting Region presses to arm Petting Activity. When disabled, the Petting Region becomes ordinary body area so pressing and dragging anywhere on Catbone performs drag-and-drop.
_Avoid_: Petting mode, affection toggle

**Petting Pose**:
A dedicated three-frame forward sitting pose with closed eyes: relaxed, one-pixel left wiggle, and one-pixel right wiggle. Active Petting Activity selects the left or right frame from current Petting Stroke direction rather than running an autonomous loop. Paused rubbing, Petting Hold, and reduced-motion mode use the relaxed frame.
_Avoid_: Petting sprite, happy animation

**Tracking Pose**:
The pet pose selected from pointer direction while pointer activity is occurring; its forward-facing frame is also the normal sitting pose.
_Avoid_: Idle animation, default state

**Interaction Priority**:
The ordering that decides which visible pet behavior wins when user activities overlap: pause/fullscreen hiding, body drag, active Petting Activity, Typing Activity, Petting Hold, Tracking Pose, Typing Hold, then normal sitting. Lower-priority activity observed during hiding, dragging, or active Petting Activity is discarded rather than queued. If keys remain held when Petting Activity ends, the ongoing Typing Activity becomes visible immediately instead of entering Petting Hold.
_Avoid_: State override, animation priority

**Pet Behavior**:
The deep module and sole owner of companion state, timers, Interaction Priority, Stationary Placement, drag activity and semantic wobble, gesture progress, Typing Activity and Typing Hold, Tracking Pose arbitration, Hiding Reasons, and Petting Heart lifetimes. Its active behavior set is normal sitting/Tracking Pose, Typing Activity/Typing Hold, body drag, Petting Activity/Petting Hold, and pause/fullscreen hiding. Callers supply monotonic time with every Behavior Activity and through explicit advancement; the implementation never reads the system clock. Its implementation does not own GTK event handling, raw input capture, input repeat suppression, settings persistence, sprite geometry, numeric sprite frames, viewport coordinates, or raster drawing.
_Avoid_: Pet state machine, behavior service

**Behavior Snapshot**:
The immutable, side-effect-free output of Pet Behavior consumed by Companion Presentation for both the desktop overlay and Pet Preview. It contains the winning activity, semantic pose and direction or variant, normalized Stationary Placement, derived visibility, and immutable Petting Heart states with lifetime progress, drift direction, and static or moving mode. It never contains sprite sheets, numeric frame indexes, GTK objects, screen coordinates, clocks, or private transition flags. Reading a Behavior Snapshot never advances time or changes behavior.
_Avoid_: Render state, animation payload

**Behavior Activity**:
A semantic input crossing the Pet Behavior seam with caller-supplied monotonic time: an already-classified Tracking Pose direction; a new physical Typing Step; whether any key remains held; a primary press already classified as Petting Region or body; normalized drag movement; primary release; a Hiding Reason change; a behavior-related Live Setting change; or explicit time advancement. Input adapters suppress kernel repeats and combine held keys before producing Behavior Activity. GTK objects, raw evdev records, pointer pixels, viewport dimensions, and sprite geometry never cross this seam.
_Avoid_: Input event, GTK event

**Behavior Advancement**:
The explicit operation that moves Pet Behavior to a caller-supplied monotonic time and performs time-driven transitions such as hold completion, drag wobble steps, Petting Heart emission, and Petting Heart expiry. The overlay tick advances behavior once before overlay and Pet Preview read the same pure Behavior Snapshot.
_Avoid_: Tick update, snapshot time

**Hiding Reason**:
One independently tracked cause that makes the companion invisible, currently user pause or fullscreen hiding. The companion remains hidden while any Hiding Reason is active. Entering a reason consumes active and held reactions; clearing one reason cannot reveal the companion while another remains active.
_Avoid_: Paused flag, hidden state

**Companion Presentation**:
The module that converts Behavior Snapshot plus viewport and pet-size information into sprite selection, numeric frame indexes, draw transforms, input geometry, Petting Region mapping, and Petting Heart drawing instructions. It owns sprite geometry, dead-zone and direction classification, viewport conversion, and pixel-scale policy. The desktop overlay and Pet Preview are rendering adapters that consume its output; neither reconstructs Interaction Priority.
_Avoid_: Sprite renderer, presentation service

**Pet Controller**:
The settings surface used to preview, configure, pause, reset, or quit the desktop companion. Hiding the controller does not stop the companion.
_Avoid_: Dashboard, control panel, launcher

**Live Setting**:
A reversible preference whose saved value and visible effect update together as soon as the user changes it.
_Avoid_: Option, pending change

**Pet Preview**:
The controller's visual-only representation of the active companion and its current behavior. It mirrors Petting Activity and other visible states from the desktop pet but does not accept petting or drag-and-drop gestures itself.
_Avoid_: Thumbnail, avatar

**Background Mode**:
A launch mode that starts the companion without initially showing the Pet Controller.
_Avoid_: Headless mode, minimized mode

**Silent Behavior**:
The current product plan contains no audio: no purring, meows, sound effects, speech, or voice. Audio may be reconsidered in a future update, but it is not part of current behavior or settings.
_Avoid_: Muted mode, sound-disabled state

## Pet Behavior Verification

The Pet Behavior interface is the test surface. Required deterministic scenarios cover:

- Stationary Placement never roaming autonomously.
- Press-origin classification and lock for Petting Region versus body drag.
- Silent release before a complete Petting Stroke.
- The 25%-width Petting Stroke threshold rejecting pointer jitter.
- Petting Region exit pausing progress and re-entry resuming it.
- Petting Heart cadence, maximum count, motion, fade, and expiry.
- Petting Hold duration and every higher-priority interruption.
- Typing Activity being discarded during petting and continuing held typing taking over after release.
- Pause/fullscreen hiding consuming active and held behavior.
- Disabled Petting Reactions converting the head to body drag area.
- Reduced motion using the relaxed Petting Pose and one static Petting Heart.
- Behavior Snapshot exposing visible state without private transition flags or timers.
