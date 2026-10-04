# Optional picture API

Use only the needed helper; existing camera and renderer code remains usable.
No added analysis, report or preview is required. Import the chosen functions
from picture-tools.js. These helpers do not choose style or camera paths.

## frame2D: Canvas / DOM target framing
`frame2D({x,y,width,height},{width,height},{coverage,anchor:[.5,.5]})`
fits an actual target rectangle at the viewport anchor. coverage is an explicit
scalar or `[x,y]` fraction in `(0,1]`. Returns `{scale,x,y,matrix}` for Canvas
setTransform or DOM transform-origin `0 0`/CSS matrix. Coordinates are world
coordinates before that transform. Choose cropping and overscan in the job.

## frame3D: perspective target framing
`frame3D({min:[x,y,z],max:[x,y,z]},{direction,up:[0,1,0],fov,aspect,coverage,near:.01})`
fits all eight world bounding-box corners. direction points from target toward
camera; fov is vertical degrees. Returns `{position,target,up,distance}` for
a perspective camera. Match its fov/aspect/near. In Three.js use actual
`Box3().setFromObject`, camera.position/up.fromArray and lookAt(...target).
Geometry bounds do not establish visible detail, occlusion or texture quality.

## createPictureBindings: optional native setters
`createPictureBindings(edit,{views,values})` creates `apply(seconds)`. views maps
shot IDs to `(setup,state)=>...`; values maps property IDs to
`(value,state)=>...` or arrays of those callbacks. One global music-linked
progress can drive camera, foreground and background at different speeds.
Every compiled shot visit and sampled property needs a handler; missing handlers
throw. Example: `values:{'world.travel':[p=>camera.position.x=p*30,
p=>foreground.position.x=p*60]}`. Paths and speeds are job decisions.

Each view handler restores its full setup/visibility. Property handlers assign
absolute values; do not accumulate from previous frames. Decode media and render
after apply. Native callbacks still need to be seek-safe: helpers cannot certify
their pixels, determinism or beauty. Use direct setters when already implemented.
