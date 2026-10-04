// Renderer-neutral framing and explicit edit-to-picture bindings. No visual style.
const finite = n => typeof n === 'number' && Number.isFinite(n);
function check(ok, message) { if (!ok) throw new Error(`BeatScope picture: ${message}`); }
function vector(v, length, name) {
  check(Array.isArray(v) && v.length === length && v.every(finite), `${name} needs ${length} finite numbers`);
  return v;
}
function coverage(value) {
  const pair = finite(value) ? [value, value] : vector(value, 2, 'coverage');
  check(pair.every(n => n > 0 && n <= 1), 'coverage must be in (0,1]');
  return pair;
}
const dot = (a, b) => a.reduce((n, v, i) => n + v * b[i], 0);
const cross = (a, b) => [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
function unit(v, name) {
  vector(v, 3, name);
  const length = Math.hypot(...v);
  check(length > 1e-12, `${name} cannot be zero or parallel to the viewing direction`);
  return v.map(n => n / length);
}

/** Frame a target rectangle in untransformed world coordinates.
 * coverage is an explicit fraction of the viewport, not a shot-name preset.
 * Apply matrix to a world wrapper (origin 0,0) or Canvas setTransform.
 * The caller owns source cropping, overscan and any animated interpolation.
 */
export function frame2D(target, viewport, {coverage: fill, anchor = [.5, .5]} = {}) {
  check(target && [target.x, target.y, target.width, target.height].every(finite)
    && target.width > 0 && target.height > 0, 'target needs a positive finite rectangle');
  check(viewport && [viewport.width, viewport.height].every(finite)
    && viewport.width > 0 && viewport.height > 0, 'viewport needs positive finite dimensions');
  vector(anchor, 2, 'anchor');
  check(anchor.every(n => n >= 0 && n <= 1), 'anchor must be in [0,1]');
  const c = coverage(fill);
  const scale = Math.min(viewport.width*c[0]/target.width, viewport.height*c[1]/target.height);
  const x = viewport.width*anchor[0] - (target.x+target.width/2)*scale;
  const y = viewport.height*anchor[1] - (target.y+target.height/2)*scale;
  return {scale, x, y, matrix: [scale, 0, 0, scale, x, y]};
}

/** Fit a world-axis bounding box to a perspective camera, including its depth.
 * direction points from the target toward the camera. fov is vertical degrees.
 * Pass actual world bounds after applying object motion. This does not test
 * occlusion, texture quality, or the camera's far plane, or choose a shot angle.
 */
export function frame3D(bounds, {direction, up = [0,1,0], fov, aspect, coverage: fill, near = .01} = {}) {
  check(bounds && Array.isArray(bounds.min) && Array.isArray(bounds.max), 'bounds need min/max vectors');
  const min = vector(bounds.min, 3, 'bounds.min'), max = vector(bounds.max, 3, 'bounds.max');
  check(max.every((n, i) => n >= min[i]) && max.some((n, i) => n > min[i]), 'bounds need nonzero ordered extents');
  check(finite(fov) && fov > 0 && fov < 180 && finite(aspect) && aspect > 0
    && finite(near) && near > 0, 'invalid perspective camera');
  const c = coverage(fill), backward = unit(direction, 'direction');
  const right = unit(cross(unit(up, 'up'), backward), 'camera right');
  const vertical = cross(backward, right);
  const target = min.map((n, i) => n+(max[i]-n)/2);
  const tanV = Math.tan(fov*Math.PI/360)*c[1], tanH = Math.tan(fov*Math.PI/360)*aspect*c[0];
  let distance = 0;
  for (let mask = 0; mask < 8; mask++) {
    const p = target.map((n, i) => (mask & (1 << i) ? max[i] : min[i])-n);
    const depth = dot(p, backward);
    distance = Math.max(distance, depth+near, depth+Math.abs(dot(p, right))/tanH,
      depth+Math.abs(dot(p, vertical))/tanV);
  }
  return {position: target.map((n, i) => n+backward[i]*distance), target, up: vertical, distance};
}

/** Apply each sampled edit through declared native renderer functions.
 * One property may fan out to several layers. Views run before properties.
 * Setters assign absolute sampled values, never accumulate previous-frame state.
 * Media decoding and rendering happen after apply(), in the caller's renderer.
 */
export function createPictureBindings(edit, {views, values = {}} = {}) {
  check(typeof edit?.at === 'function' && Array.isArray(edit.cuts), 'compiled edit required');
  const shotHandlers = new Map(Object.entries(views || {}));
  check([...shotHandlers.values()].every(fn => typeof fn === 'function'), 'views need functions');
  for (const cut of edit.cuts) check(shotHandlers.has(cut.shot), `unbound shot ${cut.shot}`);
  const writers = new Map(Object.entries(values).map(([id, value]) => {
    const fns = Array.isArray(value) ? [...value] : [value];
    check(fns.length && fns.every(fn => typeof fn === 'function'), `invalid binding ${id}`);
    return [id, fns];
  }));
  return {
    apply(time) {
      const state = edit.at(time), entries = Object.entries(state.values);
      check(shotHandlers.has(state.view.id), `unbound shot ${state.view.id}`);
      for (const [id] of entries) check(writers.has(id), `unbound property ${id}`);
      shotHandlers.get(state.view.id)(state.view.setup, state);
      for (const [id, value] of entries) for (const write of writers.get(id)) write(value, state);
      return state;
    },
  };
}
