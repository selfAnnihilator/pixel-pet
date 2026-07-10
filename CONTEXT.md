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

**Tracking Pose**:
The pet pose selected from pointer direction while pointer activity is occurring; its forward-facing frame is also the normal sitting pose.
_Avoid_: Idle animation, default state

**Interaction Priority**:
The ordering that decides which visible pet behavior wins when user activities overlap: hiding, dragging, Typing Activity, pointer tracking, Typing Hold, then normal sitting. Lower-priority activity observed during hiding or dragging is discarded rather than queued.
_Avoid_: State override, animation priority
