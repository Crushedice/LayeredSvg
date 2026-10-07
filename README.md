# LayeredSvg

## Nix eye

A layered 2.5D eye built from painted frames: frame-swap blinks, saccades,
a swept glow mask over the circuit lines, and affect states
(`idle`, `sharp`, `engaged`, `reticent`, `flat`).

```
assets-src/nix-eye/        source PNGs (base, iris, glow, blink-02 … blink-09-closed)
tools/build_eye_layers.py  turns the sources into web layers
prototype/nix-eye/         demo page + reusable eye.css / eye.js
  layers/                  generated: webp layers, sclera.svg clip, layers.css/json
```

### Rebuild the layers

```sh
pip install opencv-python-headless numpy pillow
python3 tools/build_eye_layers.py
```

The script:

- traces the eye opening in `base.png` into `sclera.svg` (the iris clip path),
- splits the pupil slit off the iris and inpaints the iris underneath, so the
  pupil can be scaled on its own,
- crops each blink frame to the eye region with a feathered edge and cuts the
  eye opening out of it, so the live iris keeps moving through a blink and
  while a half-closed lid is held,
- crops the glow lines and writes every layer's position into `layers.css`.

### Run the demo

```sh
cd prototype/nix-eye && python3 -m http.server 8000
# open http://localhost:8000
```

### Using it elsewhere

`eye.js` exports `mountEye(rootEl, { blinkStyle, onState })`, which returns
`{ setAffect, setBlinkStyle, blink, destroy }`. All visuals per affect are CSS
custom properties keyed on `data-affect`, so a host component (e.g. a Blazor
component with an `Affect` parameter) only has to set that attribute and call
`setAffect` from JS interop.
