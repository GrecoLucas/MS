// Low-poly 3D viewer. The Python server owns the simulation; this page only draws it.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const KM = 60; // scene units per kilometre
const STATUS = { ok: 0x22c55e, low: 0xf59e0b, empty: 0xef4444, crowded: 0x3b82f6, full: 0x8b5cf6 };
const PROFILE = { commuter: 0x2563eb, casual: 0xf59e0b };
const BUILDINGS = [0xf2e8d5, 0xe8c9a0, 0xd9a679, 0xc9d6df, 0xf4b9a0, 0xb8c4d6, 0xe6d3c1];
const ROOFS = [0xb45309, 0x9a3412, 0x7c2d12, 0x92400e];
const GREENS = [0x3f8f4f, 0x4fa35d, 0x2f7d46, 0x5fae5a];
const PRESETS = {
  'Baseline': { rebalancing: 'none' },
  'Threshold van': { rebalancing: 'threshold' },
  'Predictive': { rebalancing: 'predictive' },
  'Incentives': { rebalancing: 'none', incentive_discount: 0.5 },
  'Small fleet': { rebalancing: 'threshold', occupancy: 0.3 },
  'Rainy day': { rebalancing: 'threshold', weather: 'rain' },
  'Virtual zones': { rebalancing: 'threshold', virtual_zones: 3 },
};

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function seeded(seed) { // mulberry32: the city looks the same on every load
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- renderer and lights

const canvas = $('scene');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xa9d8f5);
scene.fog = new THREE.Fog(0xa9d8f5, 420, 1300);

const camera = new THREE.PerspectiveCamera(42, 1, 1, 4000);
camera.position.set(60, 190, 250);
const controls = new OrbitControls(camera, canvas);
controls.target.set(10, 0, 0);
controls.enableDamping = true;
controls.maxPolarAngle = 1.45;
controls.minDistance = 25;
controls.maxDistance = 800;

const hemisphere = new THREE.HemisphereLight(0xdff1ff, 0x6b8f4e, 1.2);
scene.add(hemisphere);
const sun = new THREE.DirectionalLight(0xfff2d6, 2.6);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -300, right: 300, top: 220, bottom: -220, near: 10, far: 1400 });
sun.shadow.bias = -0.0006;
scene.add(sun, sun.target);
const sunDisc = new THREE.Mesh(new THREE.IcosahedronGeometry(22, 1), new THREE.MeshBasicMaterial({ color: 0xffe08a, fog: false }));
const moonDisc = new THREE.Mesh(new THREE.IcosahedronGeometry(14, 1), new THREE.MeshBasicMaterial({ color: 0xdfe7ff, fog: false }));
scene.add(sunDisc, moonDisc);

function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

// ---------------------------------------------------------------- low-poly building blocks

const flat = (color, extra = {}) => new THREE.MeshLambertMaterial({ color, flatShading: true, ...extra });
const merged = (parts) => mergeGeometries(parts.map((g) => (g.index ? g.toNonIndexed() : g)));
const box = (w, h, d, x = 0, y = 0, z = 0) => new THREE.BoxGeometry(w, h, d).translate(x, y, z);

function bikeGeometry() { // points along +z
  const wheel = (z) => new THREE.TorusGeometry(0.46, 0.08, 4, 8).rotateY(Math.PI / 2).translate(0, 0.5, z);
  return merged([wheel(0.68), wheel(-0.68), box(0.09, 0.09, 1.36, 0, 0.82, 0),
    box(0.09, 0.5, 0.09, 0, 1.02, -0.32), box(0.3, 0.08, 0.34, 0, 1.3, -0.34),
    box(0.09, 0.62, 0.09, 0, 1.04, 0.62), box(0.66, 0.08, 0.09, 0, 1.36, 0.62)]);
}

function personGeometry() {
  return merged([new THREE.CylinderGeometry(0.2, 0.32, 1.0, 5).translate(0, 0.5, 0),
    new THREE.IcosahedronGeometry(0.27, 0).translate(0, 1.27, 0)]);
}

const dummy = new THREE.Object3D();
const tint = new THREE.Color();

function instanced(geometry, material, count, shadows = true) {
  const mesh = new THREE.InstancedMesh(geometry, material, count);
  mesh.count = 0;
  mesh.frustumCulled = false;
  mesh.castShadow = shadows;
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.setColorAt(0, tint.set(0xffffff)); // allocates the per-instance colours
  return mesh;
}

function place(mesh, index, x, y, z, yaw = 0, scale = 1, color = null, tilt = 0) {
  dummy.position.set(x, y, z);
  dummy.rotation.set(0, yaw, tilt);
  if (typeof scale === 'number') dummy.scale.setScalar(scale); else dummy.scale.set(...scale);
  dummy.updateMatrix();
  mesh.setMatrixAt(index, dummy.matrix);
  if (color !== null) mesh.setColorAt(index, tint.set(color));
}

function commit(mesh, count) {
  mesh.count = count;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}

function makeLabel() {
  const surface = document.createElement('canvas');
  surface.width = 256; surface.height = 96;
  const texture = new THREE.CanvasTexture(surface);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: texture, depthTest: false, transparent: true, sizeAttenuation: false }));
  sprite.scale.set(0.085, 0.032, 1);
  sprite.renderOrder = 10;
  sprite.userData = { surface, texture, key: '' };
  return sprite;
}

function setLabel(sprite, text, color = '#ffffff') {
  const { surface, texture, key } = sprite.userData;
  if (key === text + color) return;
  sprite.userData.key = text + color;
  const ctx = surface.getContext('2d');
  ctx.clearRect(0, 0, 256, 96);
  ctx.fillStyle = 'rgba(15,23,42,0.85)';
  ctx.beginPath();
  ctx.roundRect(4, 10, 248, 76, 24);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.font = `700 ${text.length > 9 ? 34 : 46}px system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 128, 50);
  texture.needsUpdate = true;
}

// Moving things are drawn with a few instanced meshes shared by the whole scene.
const bikeMaterial = flat(0xffffff);
const dockedBikes = instanced(bikeGeometry(), bikeMaterial, 1200);
const movingBikes = instanced(bikeGeometry(), bikeMaterial, 600);
const riders = instanced(personGeometry(), flat(0xffffff), 800);
const waiters = instanced(personGeometry(), flat(0xffffff), 400);
scene.add(dockedBikes, movingBikes, riders, waiters);

// ---------------------------------------------------------------- sky, clouds and rain

const SKY = [[0, 0x0b1230], [5, 0x1b2350], [6.5, 0xf7a66b], [8, 0xa9d8f5], [17, 0xa9d8f5],
  [19, 0xf48a5a], [20.5, 0x1b2350], [24, 0x0b1230]];
const skyColor = new THREE.Color();
const grey = new THREE.Color(0x8793a3);

function skyAt(hour) {
  let i = 1;
  while (i < SKY.length - 1 && SKY[i][0] < hour) i++;
  const [h0, c0] = SKY[i - 1];
  const [h1, c1] = SKY[i];
  return skyColor.set(c0).lerp(tint.set(c1), clamp((hour - h0) / (h1 - h0), 0, 1));
}

const cloudMaterial = flat(0xffffff, { transparent: true, opacity: 0.95 });
const clouds = [];
{
  const random = seeded(7);
  for (let i = 0; i < 16; i++) {
    const cloud = new THREE.Group();
    for (let j = 0; j < 4; j++) {
      const puff = new THREE.Mesh(new THREE.IcosahedronGeometry(9 + random() * 8, 0), cloudMaterial);
      puff.position.set((j - 1.5) * 13 + random() * 6, random() * 5, random() * 10);
      puff.scale.y = 0.6;
      puff.castShadow = true; // cloud shadows drift over the town
      cloud.add(puff);
    }
    cloud.position.set((random() - 0.5) * 1000, 105 + random() * 45, (random() - 0.5) * 700);
    clouds.push(cloud);
    scene.add(cloud);
  }
}

const RAIN = 2600;
const rainPositions = new Float32Array(RAIN * 6);
const rain = new THREE.LineSegments(new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({ color: 0xe6f0ff, transparent: true, opacity: 0.8 }));
rain.geometry.setAttribute('position', new THREE.BufferAttribute(rainPositions, 3));
rain.frustumCulled = false;
rain.visible = false;
scene.add(rain);
for (let i = 0; i < RAIN; i++) {
  rainPositions[i * 6] = (Math.random() - 0.5) * 700;
  rainPositions[i * 6 + 1] = Math.random() * 170;
  rainPositions[i * 6 + 2] = (Math.random() - 0.5) * 520;
}

let overcast = 0; // 0 clear .. 1 rain, eased so the weather changes smoothly

function updateSky(hour, weather, dt) {
  const goal = weather === 'rain' ? 1 : weather === 'cloudy' ? 0.55 : 0;
  overcast += (goal - overcast) * Math.min(1, dt * 1.5);
  const daylight = clamp(Math.sin(((hour - 6) / 12) * Math.PI) * 1.6 + 0.15, 0, 1);
  const sky = skyAt(hour).lerp(grey.clone().multiplyScalar(0.35 + 0.65 * daylight), overcast * 0.8);
  scene.background.copy(sky);
  scene.fog.color.copy(sky);
  scene.fog.near = 420 - 200 * overcast;
  scene.fog.far = 1300 - 500 * overcast;
  const angle = ((hour - 6) / 12) * Math.PI;
  sun.position.set(Math.cos(angle) * 420, Math.max(60, Math.sin(angle) * 480), 180).add(sun.target.position);
  sun.intensity = (0.25 + 3.8 * daylight) * (1 - 0.6 * overcast);
  sun.color.set(daylight < 0.6 ? 0xffc58a : 0xfff2d6);
  hemisphere.intensity = (1.5 + 1.7 * daylight) * (1 - 0.2 * overcast);
  hemisphere.color.set(daylight < 0.25 ? 0x9db4ff : 0xdff1ff);
  sunDisc.position.set(Math.cos(angle) * 1500, Math.sin(angle) * 1100, -600);
  moonDisc.position.set(-Math.cos(angle) * 1500, -Math.sin(angle) * 1100, -600);
  sunDisc.visible = overcast < 0.5;
  cloudMaterial.color.setScalar((0.35 + 0.65 * daylight) * (1 - 0.45 * overcast));
  clouds.forEach((cloud, i) => {
    cloud.visible = i < 4 + Math.round(12 * Math.min(1, overcast * 1.6));
    cloud.position.x += dt * 4;
    if (cloud.position.x > 520) cloud.position.x = -520;
  });
  rain.visible = overcast > 0.7;
  if (rain.visible) {
    const fall = dt * 190;
    for (let i = 0; i < RAIN; i++) {
      let y = rainPositions[i * 6 + 1] - fall;
      if (y < 0) y += 170;
      rainPositions[i * 6 + 1] = y;
      rainPositions[i * 6 + 3] = rainPositions[i * 6] + 0.6;
      rainPositions[i * 6 + 4] = y + 3.4;
      rainPositions[i * 6 + 5] = rainPositions[i * 6 + 2];
    }
    rain.geometry.attributes.position.needsUpdate = true;
    rain.position.set(controls.target.x, 0, controls.target.z);
  }
}

// ---------------------------------------------------------------- static world

let world = null;      // group rebuilt whenever a scenario starts
let nodes = [];        // scene position of every station, then the depot
let routes = null;     // road network used to draw movement
let stationViews = []; // per-station handles updated on every state
let vehicleViews = [];
let depotLabel = null;
let pickTargets = [];

function disposeWorld() {
  if (!world) return;
  world.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
    const materials = [].concat(object.material || []);
    materials.forEach((material) => { if (material.map) material.map.dispose(); material.dispose(); });
  });
  scene.remove(world);
}

function buildRoads(points) {
  const n = points.length;
  const length = (a, b) => points[a].distanceTo(points[b]);
  const edges = new Set();
  const link = (a, b) => edges.add(a < b ? `${a}-${b}` : `${b}-${a}`);
  for (let a = 0; a < n; a++) { // two nearest neighbours
    const others = [...Array(n).keys()].filter((b) => b !== a).sort((p, q) => length(a, p) - length(a, q));
    others.slice(0, 2).forEach((b) => link(a, b));
  }
  const parent = [...Array(n).keys()]; // then join what is still disconnected
  const find = (a) => (parent[a] === a ? a : (parent[a] = find(parent[a])));
  edges.forEach((edge) => { const [a, b] = edge.split('-').map(Number); parent[find(a)] = find(b); });
  const pairs = [];
  for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) pairs.push([a, b]);
  pairs.sort((p, q) => length(...p) - length(...q)).forEach(([a, b]) => {
    if (find(a) !== find(b)) { link(a, b); parent[find(a)] = find(b); }
  });
  const dist = Array.from({ length: n }, () => Array(n).fill(Infinity));
  const next = Array.from({ length: n }, () => Array(n).fill(-1));
  for (let a = 0; a < n; a++) { dist[a][a] = 0; next[a][a] = a; }
  const list = [...edges].map((edge) => edge.split('-').map(Number));
  list.forEach(([a, b]) => { dist[a][b] = dist[b][a] = length(a, b); next[a][b] = b; next[b][a] = a; });
  for (let k = 0; k < n; k++) for (let a = 0; a < n; a++) for (let b = 0; b < n; b++) {
    if (dist[a][k] + dist[k][b] < dist[a][b]) { dist[a][b] = dist[a][k] + dist[k][b]; next[a][b] = next[a][k]; }
  }
  const cache = new Map();
  function path(a, b) {
    const key = a * 1000 + b;
    if (!cache.has(key)) {
      const stops = [points[a]];
      for (let at = a; at !== b;) { at = next[at][b]; stops.push(points[at]); }
      if (stops.length === 1) stops.push(points[a]);
      const cumulative = [0];
      for (let i = 1; i < stops.length; i++) cumulative.push(cumulative[i - 1] + stops[i].distanceTo(stops[i - 1]));
      cache.set(key, { stops, cumulative, total: cumulative[cumulative.length - 1] });
    }
    return cache.get(key);
  }
  return { edges: list, path };
}

const heading = new THREE.Vector3();

/** Position (into `out`) and yaw at fraction f of the road path from a to b. */
function along(a, b, f, out, side = 0) {
  const { stops, cumulative, total } = routes.path(a, b);
  const d = clamp(f, 0, 1) * total;
  let i = 1;
  while (i < stops.length - 1 && cumulative[i] < d) i++;
  const span = cumulative[i] - cumulative[i - 1];
  out.lerpVectors(stops[i - 1], stops[i], span ? (d - cumulative[i - 1]) / span : 0);
  heading.subVectors(stops[i], stops[i - 1]);
  if (heading.lengthSq() < 1e-6) return null;
  heading.normalize();
  out.x += heading.z * side; // keep to one side of the road
  out.z -= heading.x * side;
  return Math.atan2(heading.x, heading.z);
}

function segmentDistance(px, pz, a, b) {
  const dx = b.x - a.x, dz = b.z - a.z;
  const t = clamp(((px - a.x) * dx + (pz - a.z) * dz) / (dx * dx + dz * dz || 1), 0, 1);
  return Math.hypot(px - a.x - t * dx, pz - a.z - t * dz);
}

function buildWorld(state) {
  disposeWorld();
  world = new THREE.Group();
  scene.add(world);
  const random = seeded(442);
  const stations = state.stations;
  nodes = stations.map((s) => new THREE.Vector3(s.x * KM, 0, -s.y * KM));
  nodes.push(new THREE.Vector3(0, 0, 0)); // the depot is the origin of the map
  routes = buildRoads(nodes);
  const roadDistance = (x, z) => Math.min(...routes.edges.map(([a, b]) => segmentDistance(x, z, nodes[a], nodes[b])));
  const nodeDistance = (x, z) => Math.min(...nodes.map((p) => Math.hypot(x - p.x, z - p.z)));

  // Ground: flat where the city is, gentle hills far away.
  const xs = nodes.map((p) => p.x), zs = nodes.map((p) => p.z);
  const centre = new THREE.Vector3((Math.min(...xs) + Math.max(...xs)) / 2, 0, (Math.min(...zs) + Math.max(...zs)) / 2);
  const width = Math.max(...xs) - Math.min(...xs) + 900, depth = Math.max(...zs) - Math.min(...zs) + 900;
  let ground = new THREE.PlaneGeometry(width, depth, 44, 36).rotateX(-Math.PI / 2).translate(centre.x, 0, centre.z);
  const position = ground.attributes.position;
  for (let i = 0; i < position.count; i++) {
    const away = clamp((nodeDistance(position.getX(i), position.getZ(i)) - 90) / 220, 0, 1);
    position.setY(i, -0.3 + away * away * (8 + random() * 26));
  }
  ground = ground.toNonIndexed();
  const colours = new Float32Array(ground.attributes.position.count * 3);
  for (let i = 0; i < colours.length; i += 9) {
    tint.set(0x8fbf6a).offsetHSL((random() - 0.5) * 0.03, 0, (random() - 0.5) * 0.07);
    for (let j = 0; j < 9; j += 3) tint.toArray(colours, i + j);
  }
  ground.setAttribute('color', new THREE.BufferAttribute(colours, 3));
  ground.computeVertexNormals();
  const land = new THREE.Mesh(ground, flat(0xffffff, { vertexColors: true }));
  land.receiveShadow = true;
  world.add(land);
  sun.target.position.copy(centre);

  // Roads.
  const roads = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.12, 1), flat(0x59616d), routes.edges.length);
  routes.edges.forEach(([a, b], i) => {
    const from = nodes[a], to = nodes[b];
    dummy.position.set((from.x + to.x) / 2, 0.06, (from.z + to.z) / 2);
    dummy.rotation.set(0, Math.atan2(to.x - from.x, to.z - from.z), 0);
    dummy.scale.set(3.4, 1, from.distanceTo(to));
    dummy.updateMatrix();
    roads.setMatrixAt(i, dummy.matrix);
  });
  roads.receiveShadow = true;
  world.add(roads);

  // Buildings and trees: dense and tall in the centre, houses and trees outside.
  const blocks = [], houses = [], trees = [];
  const free = (x, z, radius) => roadDistance(x, z) > radius + 2.2 && nodeDistance(x, z) > radius + 9
    && blocks.concat(houses).every((b) => Math.hypot(b.x - x, b.z - z) > radius + b.r + 0.8);
  const scatter = (origin, count, reach, make) => {
    for (let i = 0; i < count; i++) {
      const angle = random() * Math.PI * 2, far = 12 + random() * reach;
      make(origin.x + Math.cos(angle) * far, origin.z + Math.sin(angle) * far);
    }
  };
  stations.forEach((s, i) => {
    const density = { center: [30, 2, 5], intermediate: [14, 8, 10], periphery: [2, 9, 16] }[s.zone];
    scatter(nodes[i], density[0], 40, (x, z) => {
      const w = 4 + random() * 4, d = 4 + random() * 4;
      const h = s.zone === 'center' ? 6 + random() * 15 : 4 + random() * 6;
      if (free(x, z, Math.max(w, d) * 0.72)) blocks.push({ x, z, w, d, h, r: Math.max(w, d) * 0.72, yaw: random() * Math.PI });
    });
    scatter(nodes[i], density[1], 48, (x, z) => {
      const w = 3.6 + random() * 1.8;
      if (free(x, z, w * 0.75)) houses.push({ x, z, w, h: 2.6 + random() * 1.2, r: w * 0.75, yaw: random() * Math.PI });
    });
    scatter(nodes[i], density[2], 60, (x, z) => { if (free(x, z, 1.5)) trees.push({ x, z, s: 0.8 + random() * 0.8 }); });
  });
  for (let i = 0; i < 380; i++) { // woods around the town
    const x = centre.x + (random() - 0.5) * (width - 120), z = centre.z + (random() - 0.5) * (depth - 120);
    if (nodeDistance(x, z) > 70 && roadDistance(x, z) > 6) trees.push({ x, z, s: 0.9 + random() * 1.3, wild: true });
  }
  const heightAt = (x, z) => { // trees outside the town stand on the hills
    const away = clamp((nodeDistance(x, z) - 90) / 220, 0, 1);
    return away * away * 14;
  };
  const walls = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), flat(0xffffff), blocks.length + houses.length);
  const pick = (palette) => palette[Math.floor(random() * palette.length)];
  blocks.forEach((b, i) => place(walls, i, b.x, 0, b.z, b.yaw, [b.w, b.h, b.d], pick(BUILDINGS)));
  houses.forEach((b, i) => place(walls, blocks.length + i, b.x, 0, b.z, b.yaw, [b.w, b.h, b.w], pick(BUILDINGS)));
  const roofs = new THREE.InstancedMesh(new THREE.ConeGeometry(0.74, 1, 4).rotateY(Math.PI / 4).translate(0, 0.5, 0), flat(0xffffff), Math.max(1, houses.length));
  houses.forEach((b, i) => place(roofs, i, b.x, b.h, b.z, b.yaw, [b.w, b.w * 0.5, b.w], pick(ROOFS)));
  roofs.count = houses.length;
  const crowns = new THREE.InstancedMesh(new THREE.ConeGeometry(1.5, 4.2, 6).translate(0, 3.4, 0), flat(0xffffff), Math.max(1, trees.length));
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.28, 0.36, 1.6, 5).translate(0, 0.8, 0), flat(0x7a5a3a), Math.max(1, trees.length));
  trees.forEach((t, i) => {
    const y = t.wild ? heightAt(t.x, t.z) : 0;
    place(crowns, i, t.x, y, t.z, random() * 3, t.s, pick(GREENS));
    place(trunks, i, t.x, y, t.z, 0, t.s);
  });
  [walls, roofs, crowns, trunks].forEach((mesh) => {
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    world.add(mesh);
  });

  // Stations.
  const posts = [];
  pickTargets = [];
  stationViews = stations.map((s, i) => {
    const node = nodes[i];
    const virtual = s.kind === 'virtual';
    const columns = Math.ceil(s.capacity / 2);
    const half = virtual ? 5.6 : (columns * 0.95 + 1.4) / 2;
    const slots = [];
    for (let j = 0; j < s.capacity; j++) {
      if (virtual) {
        const angle = random() * Math.PI * 2, far = Math.sqrt(random()) * 4.4;
        slots.push({ x: Math.cos(angle) * far, z: Math.sin(angle) * far, yaw: random() * Math.PI * 2 });
      } else {
        const row = j % 2, x = (Math.floor(j / 2) - (columns - 1) / 2) * 0.95;
        slots.push({ x, z: row ? 1.45 : -1.45, yaw: row ? 0 : Math.PI });
        posts.push([node.x + x, node.z + (row ? 0.35 : -0.35)]);
      }
    }
    const group = new THREE.Group();
    group.position.copy(node);
    const base = virtual
      ? new THREE.Mesh(new THREE.CylinderGeometry(5.6, 5.6, 0.3, 20), flat(0x60a5fa, { transparent: true, opacity: 0.6 }))
      : new THREE.Mesh(new THREE.BoxGeometry(half * 2, 0.5, 5.6), flat(0xd7dde5));
    base.position.y = virtual ? 0.2 : 0.25;
    base.receiveShadow = true;
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 5.4, 6), flat(0x475569));
    pole.position.set(half + 1.3, 2.7, 0);
    pole.castShadow = true;
    const beacon = new THREE.Mesh(new THREE.OctahedronGeometry(1.0, 0), new THREE.MeshBasicMaterial({ color: STATUS.ok }));
    beacon.position.set(half + 1.3, 6.3, 0);
    const frame = new THREE.Mesh(new THREE.BoxGeometry(0.9, 4.6, 0.9), flat(0x1e293b, { transparent: true, opacity: 0.35 }));
    frame.position.set(half + 2.6, 2.5, 0);
    const level = new THREE.Mesh(new THREE.BoxGeometry(0.8, 4.5, 0.8).translate(0, 2.25, 0), new THREE.MeshBasicMaterial({ color: STATUS.ok }));
    level.position.set(half + 2.6, 0.25, 0);
    const coin = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.22, 10).rotateX(Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xfacc15 }));
    coin.position.set(half + 1.3, 8.3, 0);
    coin.visible = false;
    const label = makeLabel();
    label.position.set(0, 10.5, 0);
    const target = new THREE.Mesh(new THREE.CylinderGeometry(half + 3, half + 3, 9, 8).translate(0, 4.5, 0),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
    target.userData.station = i;
    pickTargets.push(target);
    group.add(base, pole, beacon, frame, level, coin, label, target);
    world.add(group);
    return { node, slots, half, beacon, level, coin, label };
  });
  const docks = new THREE.InstancedMesh(new THREE.BoxGeometry(0.2, 0.8, 0.2).translate(0, 0.9, 0), flat(0x475569), Math.max(1, posts.length));
  posts.forEach(([x, z], i) => place(docks, i, x, 0, z));
  docks.count = posts.length;
  world.add(docks);

  // Depot: workshop and garage of the vans.
  const depot = new THREE.Group();
  const home = nodes[nodes.length - 1];
  depot.position.set(home.x, 0, home.z - 9);
  const hall = new THREE.Mesh(new THREE.BoxGeometry(13, 5, 7).translate(0, 2.5, 0), flat(0x64748b));
  const roof = new THREE.Mesh(new THREE.CylinderGeometry(4.6, 4.6, 13.6, 3).rotateZ(Math.PI / 2).translate(0, 6.9, 0), flat(0xf97316));
  roof.scale.set(1, 0.55, 0.92);
  roof.position.y = 2.0;
  const door = new THREE.Mesh(new THREE.BoxGeometry(4.4, 3.4, 0.2).translate(-2.6, 1.7, 3.55), flat(0x1e293b));
  const yard = new THREE.Mesh(new THREE.BoxGeometry(16, 0.3, 8).translate(0, 0.15, 6), flat(0xb8c0cc));
  [hall, roof].forEach((mesh) => { mesh.castShadow = true; });
  yard.receiveShadow = true;
  depotLabel = makeLabel();
  depotLabel.position.set(0, 13, 0);
  depot.add(hall, roof, door, yard, depotLabel);
  world.add(depot);

  // Vans.
  vehicleViews = state.vehicles.map(() => {
    const van = new THREE.Group();
    const body = new THREE.Mesh(merged([box(2.3, 2.0, 3.6, 0, 1.7, -0.6), box(2.3, 0.25, 5.2, 0, 0.75, 0)]), flat(0xffffff));
    const cab = new THREE.Mesh(box(2.3, 1.5, 1.5, 0, 1.45, 1.85), flat(0x22c55e));
    const glass = new THREE.Mesh(box(2.0, 0.7, 0.1, 0, 1.75, 2.62), flat(0x0f172a));
    const wheel = (x, z) => new THREE.CylinderGeometry(0.55, 0.55, 0.4, 8).rotateZ(Math.PI / 2).translate(x, 0.55, z);
    const wheels = new THREE.Mesh(merged([wheel(1.1, 1.6), wheel(-1.1, 1.6), wheel(1.1, -1.6), wheel(-1.1, -1.6)]), flat(0x111827));
    [body, cab, wheels].forEach((mesh) => { mesh.castShadow = true; });
    const label = makeLabel();
    van.add(body, cab, glass, wheels);
    van.position.copy(home);
    world.add(van, label); // the label stays outside so it does not scale with the van
    return { van, label, yaw: 0 };
  });
}

// ---------------------------------------------------------------- simulation state

let state = null;
let target = 0;       // simulated time (minutes) the animation wants to reach
let playing = true;
let speed = 5;        // simulated minutes per real second
let busy = false;
let selected = null;
const users = new Map();
const history = [];

async function api(path, body) {
  const response = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function fail(error) {
  playing = false;
  $('play').textContent = 'Play';
  $('error').hidden = false;
  $('error').textContent = `Lost contact with the simulation (${error.message}). Is "python -m viz3d" still running? Reload the page to retry.`;
}

function statusOf(s) {
  if (s.available === 0) return 'empty';
  if (s.available + s.broken >= s.capacity) return 'full';
  if (s.needs) return 'low';
  if (s.crowded) return 'crowded';
  return 'ok';
}

function applyState(next, fresh = false) {
  state = next;
  if (fresh) {
    users.clear();
    history.length = 0;
    target = state.minute;
    buildWorld(state);
    fillForm(state.params);
    closeCard();
  }
  state.users.forEach((u) => users.set(u.id, u));
  const alive = new Set(state.users.map((u) => u.id));
  users.forEach((u, id) => { u.gone = !alive.has(id); });

  // Docked bikes, waiting people and station signs.
  let bikes = 0, people = 0;
  state.stations.forEach((s, i) => {
    const view = stationViews[i];
    const status = statusOf(s);
    view.beacon.material.color.set(STATUS[status]);
    view.level.material.color.set(STATUS[status]);
    view.level.scale.y = Math.max(0.02, (s.available + s.broken) / s.capacity);
    view.coin.visible = state.params.incentive_discount > 0 && s.needs;
    setLabel(view.label, `${s.available}/${s.capacity}`, status === 'empty' ? '#fca5a5' : '#ffffff');
    for (let j = 0; j < s.available + s.broken; j++) {
      const slot = view.slots[j], broken = j >= s.available;
      place(dockedBikes, bikes++, view.node.x + slot.x, broken ? 0.75 : 0.5, view.node.z + slot.z,
        slot.yaw, 0.85, broken ? 0xe11d48 : 0x14b8a6, broken ? 1.25 : 0);
    }
    for (let j = 0; j < Math.min(s.waiting, 12); j++) {
      place(waiters, people++, view.node.x + (j % 6 - 2.5) * 0.9, 0.5, view.node.z + 4 + Math.floor(j / 6), 0, 1.35, 0xf43f5e);
    }
  });
  commit(dockedBikes, bikes);
  commit(waiters, people);
  const d = state.depot;
  setLabel(depotLabel, `Depot ${d.stock} · fix ${d.repairing + d.queue}`);
  state.vehicles.forEach((v, i) => {
    const text = v.broken ? `${v.cargo}+${v.broken}/${v.capacity}` : `${v.cargo}/${v.capacity}`;
    if (vehicleViews[i]) setLabel(vehicleViews[i].label, text, v.broken ? '#fda4af' : '#bbf7d0');
  });
  if (!history.length || history[history.length - 1].minute !== state.minute) {
    history.push({ minute: state.minute, service: state.kpi.service_rate, use: state.kpi.bikes_in_use, waiting: state.kpi.users_waiting });
    if (history.length > 720) history.splice(0, history.length, ...history.filter((_, i) => i % 2 === 0));
  }
  updateHud();
  if (selected !== null) showCard(selected);
}

const spot = new THREE.Vector3();

function drawMoving(now, dt) {
  const zoom = clamp(camera.position.distanceTo(controls.target) / 150, 1, 2.6); // stay visible from far away
  let bikes = 0, people = 0;
  users.forEach((u, id) => {
    if (u.gone && now >= u.t1) { users.delete(id); return; }
    const f = u.t1 > u.t0 ? (now - u.t0) / (u.t1 - u.t0) : 1;
    const riding = u.state === 'riding';
    const yaw = along(u.from, u.to, f, spot, riding ? 0.95 : 2.1) ?? 0;
    if (riding) {
      place(movingBikes, bikes++, spot.x, 0.12, spot.z, yaw, 1.05 * zoom, 0xf8fafc);
      place(riders, people++, spot.x, 0.12 + 0.72 * zoom, spot.z, yaw, 1.05 * zoom, PROFILE[u.profile]);
    } else {
      place(riders, people++, spot.x, 0.12 + Math.abs(Math.sin(now * 9 + id)) * 0.18, spot.z, yaw, 1.2 * zoom, PROFILE[u.profile]);
    }
  });
  commit(movingBikes, bikes);
  commit(riders, people);
  state.vehicles.forEach((v, i) => {
    const view = vehicleViews[i];
    if (!view) return;
    const f = v.state === 'moving' && v.t1 > v.t0 ? (now - v.t0) / (v.t1 - v.t0) : 1;
    const yaw = along(v.from, v.to, f, spot, 0);
    if (yaw !== null) view.yaw = yaw;
    if (v.state !== 'moving') spot.z += 4.2; // park next to the platform, not on it
    view.van.position.lerp(spot.setY(0.12), Math.min(1, dt * 12));
    view.van.rotation.y = view.yaw;
    view.van.scale.setScalar(1.25 * Math.min(zoom, 2));
    view.label.position.copy(view.van.position).setY(5.5 * view.van.scale.y + 2);
  });
  stationViews.forEach((view) => {
    view.beacon.rotation.y += dt * 1.5;
    view.coin.rotation.y += dt * 3;
  });
}

// ---------------------------------------------------------------- heads-up display

const euro = (v) => `€${Math.round(v).toLocaleString('en')}`;
const percent = (v) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(1)}%`);
const minutes = (v) => (v === null || v === undefined ? '–' : `${v.toFixed(1)} min`);

function chart(id, series, colours, fixedMax = null) {
  const surface = $(id), ctx = surface.getContext('2d');
  const w = surface.width, h = surface.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = 'rgba(148,163,184,0.25)';
  ctx.strokeRect(0.5, 0.5, w - 1, h - 1);
  if (history.length < 2) return;
  const max = fixedMax ?? Math.max(1, ...series.flatMap((key) => history.map((p) => p[key] || 0)));
  const min = fixedMax ? Math.min(0.5, ...history.map((p) => p[series[0]] ?? 1)) : 0;
  series.forEach((key, k) => {
    ctx.beginPath();
    history.forEach((p, i) => {
      const x = (i / (history.length - 1)) * (w - 4) + 2;
      const y = h - 3 - (((p[key] ?? max) - min) / (max - min || 1)) * (h - 6);
      if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    });
    ctx.strokeStyle = colours[k];
    ctx.lineWidth = 1.6;
    ctx.stroke();
  });
}

function updateHud() {
  const k = state.kpi;
  $('clock').textContent = state.clock;
  $('daytype').textContent = state.weekend ? 'weekend' : 'weekday';
  $('weather').textContent = `${{ clear: '☀', cloudy: '☁', rain: '☂' }[state.weather]} ${state.weather} · ${state.temperature.toFixed(0)}°C`;
  $('demand').textContent = `${state.demand_now.toFixed(0)} req/h`;
  $('k-service').textContent = percent(k.service_rate);
  $('k-requests').textContent = k.requests.toLocaleString('en');
  $('k-unmet').textContent = k.failed_pickups.toLocaleString('en');
  $('k-unmet').className = k.failed_pickups ? 'bad' : '';
  $('k-wait').textContent = minutes(k.avg_wait_minutes);
  $('k-walk').textContent = minutes(k.avg_walk_minutes);
  $('k-inuse').textContent = k.bikes_in_use;
  $('k-waiting').textContent = k.users_waiting;
  $('k-redirected').textContent = k.redirected_trips.toLocaleString('en');
  $('k-broken').textContent = `${k.broken_bikes_now} / ${k.fleet_size}`;
  $('k-moved').textContent = k.bikes_rebalanced.toLocaleString('en');
  $('k-km').textContent = `${k.vehicle_km.toFixed(0)} km`;
  $('k-revenue').textContent = euro(k.revenue);
  $('k-opcost').textContent = euro(k.operational_cost);
  $('k-maint').textContent = euro(k.maintenance_cost);
  $('k-profit').textContent = euro(k.profit);
  $('k-profit').className = k.profit < 0 ? 'bad' : 'good';
  $('zones').innerHTML = Object.entries(k.service_rate_by_zone).map(([zone, rate]) =>
    `<div><span>${zone}</span><span class="bar"><i style="width:${(rate ?? 0) * 100}%"></i></span><b>${rate === null ? '–' : (rate * 100).toFixed(0) + '%'}</b></div>`).join('');
  chart('chart-service', ['service'], ['#38bdf8'], 1);
  chart('chart-use', ['use', 'waiting'], ['#60a5fa', '#f87171']);
}

function showCard(index) {
  const s = state.stations[index];
  if (!s) return closeCard();
  selected = index;
  const rows = [
    ['Usable bikes', `${s.available} / ${s.capacity}`], ['Broken bikes', s.broken],
    ['Users waiting', s.waiting], ['Requests', s.requests], ['Unmet requests', s.unmet],
    ['Demand served', percent(s.service)], ['Failed returns (full)', s.failed_returns],
    ['Time empty', percent(s.empty_share)], ['Time full', percent(s.full_share)],
  ];
  $('card').innerHTML = `<button class="close" aria-label="Close">×</button><h4></h4>
    <small>${s.kind === 'virtual' ? 'virtual parking zone' : 'docked station'} · ${s.zone}</small>
    <table>${rows.map(([name, value]) => `<tr><td>${name}</td><td>${value}</td></tr>`).join('')}</table>`;
  $('card').querySelector('h4').textContent = s.name;
  $('card').querySelector('.close').onclick = closeCard;
  $('card').hidden = false;
}

function closeCard() {
  selected = null;
  $('card').hidden = true;
}

// ---------------------------------------------------------------- controls

const form = $('form');
const FORMAT = {
  occupancy: (v) => `${Math.round(v * 100)}% of docks`,
  vehicles: (v) => v,
  demand_rate: (v) => `${(v * 60).toFixed(1)} req/station/h`,
  incentive_discount: (v) => (v > 0 ? `${Math.round(v * 100)}% off` : 'off'),
  mean_temperature: (v) => `${v}°C`,
  virtual_zones: (v) => v,
  capacity_scale: (v) => `×${v}`,
  failure_rate: (v) => `${(v * 100).toFixed(1)} per 100 km`,
  price_minute: (v) => `€${Number(v).toFixed(2)}`,
};

function refreshOutputs() {
  form.querySelectorAll('output').forEach((output) => {
    const name = output.dataset.for;
    output.textContent = FORMAT[name](Number(form.elements[name].value));
  });
}

function fillForm(params) {
  Object.entries(params).forEach(([name, value]) => {
    if (form.elements[name]) form.elements[name].value = value;
  });
  refreshOutputs();
}

function readForm() {
  const params = {};
  [...form.elements].forEach((field) => {
    if (field.name) params[field.name] = field.tagName === 'SELECT' && isNaN(field.value) ? field.value : Number(field.value);
  });
  return params;
}

async function restart(params) {
  busy = true;
  try { applyState(await api('/api/reset', params), true); } catch (error) { fail(error); }
  busy = false;
}

form.addEventListener('input', refreshOutputs);
form.addEventListener('submit', (event) => { event.preventDefault(); restart(readForm()); });
Object.entries(PRESETS).forEach(([name, params]) => {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = name;
  button.onclick = () => restart({ ...params, seed: Number(form.elements.seed.value) });
  $('presets').append(button);
});

function setPlaying(value) {
  playing = value;
  $('play').textContent = playing ? 'Pause' : 'Play';
}
$('play').onclick = () => setPlaying(!playing);
$('step').onclick = () => { setPlaying(false); if (state) target = state.minute + 1; };
$('speeds').onclick = (event) => {
  if (!event.target.dataset.speed) return;
  speed = Number(event.target.dataset.speed);
  [...$('speeds').children].forEach((button) => button.classList.toggle('on', button === event.target));
};
$('toggle-scenario').onclick = () => $('scenario').classList.toggle('hidden');
$('toggle-indicators').onclick = () => {
  $('indicators').classList.toggle('hidden');
  $('indicators').classList.toggle('shown');
};
window.addEventListener('keydown', (event) => {
  if (event.code === 'Space' && !['INPUT', 'SELECT', 'BUTTON'].includes(event.target.tagName)) {
    event.preventDefault();
    setPlaying(!playing);
  }
});

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
function stationAt(event) {
  pointer.set((event.clientX / window.innerWidth) * 2 - 1, -(event.clientY / window.innerHeight) * 2 + 1);
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(pickTargets, false)[0];
  return hit ? hit.object.userData.station : null;
}
let pressed = null;
canvas.addEventListener('pointerdown', (event) => { pressed = [event.clientX, event.clientY]; flight = null; });
canvas.addEventListener('pointerup', (event) => {
  if (!pressed || Math.hypot(event.clientX - pressed[0], event.clientY - pressed[1]) > 5) return; // it was a drag
  const index = stationAt(event);
  if (index === null) closeCard(); else showCard(index);
});
// Double-click a station to fly there; double-click the ground to see the whole town again.
let flight = null;
const HOME = { position: camera.position.clone(), target: controls.target.clone() };
function flyTo(position, lookAt) {
  flight = { fromPosition: camera.position.clone(), fromTarget: controls.target.clone(), position, target: lookAt, t: 0 };
}
canvas.addEventListener('dblclick', (event) => {
  const index = stationAt(event);
  if (index === null) return flyTo(HOME.position, HOME.target);
  const node = nodes[index];
  flyTo(new THREE.Vector3(node.x + 12, 17, node.z + 24), node.clone());
});
function updateFlight(dt) {
  if (!flight) return;
  flight.t = Math.min(1, flight.t + dt / 0.9);
  const ease = flight.t * flight.t * (3 - 2 * flight.t);
  camera.position.lerpVectors(flight.fromPosition, flight.position, ease);
  controls.target.lerpVectors(flight.fromTarget, flight.target, ease);
  if (flight.t === 1) flight = null;
}
canvas.addEventListener('pointermove', (event) => {
  const index = state ? stationAt(event) : null;
  const tip = $('tooltip');
  tip.hidden = index === null;
  canvas.style.cursor = index === null ? 'grab' : 'pointer';
  if (index !== null) {
    tip.textContent = state.stations[index].name;
    tip.style.left = `${event.clientX + 14}px`;
    tip.style.top = `${event.clientY + 10}px`;
  }
});

// ---------------------------------------------------------------- main loop

let last = performance.now();
function frame(time) {
  const dt = Math.min(0.1, (time - last) / 1000);
  last = time;
  if (state) {
    if (playing) target = Math.min(target + dt * speed, state.minute + Math.max(1, speed * 0.15));
    if (!busy && target > state.minute) {
      busy = true;
      api('/api/step', { minutes: Math.ceil(target - state.minute) })
        .then((next) => applyState(next), fail)
        .finally(() => { busy = false; });
    }
    const now = Math.min(target, state.minute);
    updateSky((now / 60) % 24, state.weather, dt);
    drawMoving(now, dt);
  }
  updateFlight(dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

if (window.innerWidth < 1000) $('scenario').classList.add('hidden'); // leave room for the city
api('/api/state').then((first) => applyState(first, true), fail);
requestAnimationFrame(frame);
