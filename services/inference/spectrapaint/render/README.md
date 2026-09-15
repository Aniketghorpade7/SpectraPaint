# render — the recolour engine

    light_map  =  linear_photo / base_colour               (once per photo)
    new_wall   =  light_map * target_shade * light_tint    (per Shade change)
    output     =  a * new_wall + (1 - a) * linear_photo

All steps in linear RGB, including the composite.

The Light Map's division carries three robustness refinements for real photographs (#9): a blend
toward single-brightness division as the Base Colour saturates, a ceiling on runaway values, and
noise-measured smoothing of dark regions. All three degrade to the plain division on clean,
neutral input. Their tunables live at the top of engine.py, each with the reasoning.

Kept as a pure function with no I/O, because colour correctness is analytically checkable:
build a photo as known_shading * known_base and the correct output is known_shading * target.
This is test Seam 2.
