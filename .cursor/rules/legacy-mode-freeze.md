# Legacy Mode Freeze

- Legacy mode refers to the old advanced code path selected by `view_mode=legacy`.
- Legacy behavior is frozen and must not be changed unless explicitly requested by the user.
- New feature work must target `basic` and the new `advanced` (basic-like) paths.
- Bug fixes that would alter legacy behavior require explicit approval in the task request.
