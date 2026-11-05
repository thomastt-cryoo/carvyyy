import * as THREE from "three";
import { OrbitControls } from "/vendor/three/OrbitControls.js";
import { GLTFLoader } from "/vendor/three/GLTFLoader.js";

export function createViewer(element) {
  let renderer,
    scene,
    camera,
    controls,
    mesh,
    grid,
    size,
    active = false,
    serial = 0,
    fitted = false,
    dark = true,
    keyLight,
    light = { direction: 315, angle: 35, intensity: 1.8 };
  const material = new THREE.MeshStandardMaterial({
    color: 0xb8b4ad,
    roughness: 0.85,
    metalness: 0,
  });
  function init() {
    if (renderer) return;
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(38, 1, 0.1, 10000);
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.domElement.setAttribute(
      "aria-label",
      "Interactive 3D relief. Drag to rotate, scroll to zoom, right drag to pan.",
    );
    element.append(renderer.domElement);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x606060, 0.65));
    keyLight = new THREE.DirectionalLight(0xffffff, light.intensity);
    scene.add(keyLight);
    lighting(light);
    const fill = new THREE.DirectionalLight(0xffffff, 0.25);
    fill.position.set(200, 60, -100);
    scene.add(fill);
    new ResizeObserver(resize).observe(element);
    theme(dark);
    resize();
    renderer.setAnimationLoop(() => {
      if (active) {
        controls.update();
        renderer.render(scene, camera);
      }
    });
  }
  function lighting(value) {
    light = { ...light, ...value };
    if (!keyLight) return;
    const azimuth = THREE.MathUtils.degToRad(light.direction),
      elevation = THREE.MathUtils.degToRad(light.angle);
    keyLight.position.set(
      Math.cos(azimuth) * Math.cos(elevation) * 300,
      Math.sin(elevation) * 300,
      Math.sin(azimuth) * Math.cos(elevation) * 300,
    );
    keyLight.intensity = light.intensity;
  }
  function resize() {
    if (!renderer) return;
    const w = element.clientWidth,
      h = element.clientHeight;
    if (!w || !h) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  function theme(value) {
    dark = value;
    if (!scene) return;
    scene.background = new THREE.Color(dark ? 0x101112 : 0xf0efeb);
    if (grid) {
      grid.material.opacity = dark ? 0.11 : 0.16;
      grid.material.transparent = true;
    }
  }
  function dispose() {
    if (!mesh) return;
    scene.remove(mesh);
    mesh.traverse((o) => o.geometry?.dispose());
    mesh = null;
    if (grid) {
      scene.remove(grid);
      grid.geometry.dispose();
      grid.material.dispose();
      grid = null;
    }
  }
  function fit(reset = false) {
    if (!mesh) return;
    const center = new THREE.Vector3(0, size.y / 2, 0);
    const distance =
      ((Math.max(size.z, size.x / camera.aspect) * 0.5) /
        Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))) *
      1.32;
    const direction = reset
      ? new THREE.Vector3(0.08, 1.2, 0.74).normalize()
      : camera.position.clone().sub(controls.target).normalize();
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(direction, distance + size.y);
    camera.near = 0.1;
    camera.far = Math.max(5000, distance * 20);
    camera.updateProjectionMatrix();
    controls.update();
  }
  async function load(buffer, reset = false, isCurrent = () => true) {
    init();
    const version = ++serial;
    const result = await new Promise((resolve, reject) =>
      new GLTFLoader().parse(buffer, "", resolve, reject),
    );
    if (version !== serial || !isCurrent()) {
      result.scene.traverse((o) => {
        o.geometry?.dispose();
        o.material?.dispose();
      });
      return;
    }
    dispose();
    mesh = result.scene;
    mesh.traverse((o) => {
      if (o.isMesh) {
        o.material?.dispose();
        o.material = material;
      }
    });
    mesh.rotation.x = -Math.PI / 2;
    const box = new THREE.Box3().setFromObject(mesh);
    size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    mesh.position.set(-center.x, -box.min.y, -center.z);
    scene.add(mesh);
    const span = Math.ceil((Math.max(size.x, size.z) * 1.8) / 10) * 10;
    grid = new THREE.GridHelper(
      span,
      Math.min(100, Math.ceil(span / 10)),
      0x888888,
      0x888888,
    );
    grid.position.y = -0.1;
    scene.add(grid);
    theme(dark);
    if (!fitted || reset) {
      fit(true);
      fitted = true;
    }
    resize();
  }
  return {
    load,
    lighting,
    cancelLoad: () => {
      serial++;
    },
    theme,
    fit,
    reset: () => fit(true),
    visible(value) {
      active = value;
      if (value) {
        init();
        resize();
      }
    },
    clear(keepCamera = false) {
      active = false;
      if (!keepCamera) fitted = false;
      serial++;
      dispose();
      renderer?.renderLists.dispose();
    },
    top() {
      if (mesh) {
        fit(true);
        const d = camera.position.distanceTo(controls.target);
        camera.position.set(0, d, 0.001);
        controls.update();
      }
    },
    zoom(factor) {
      if (camera) {
        camera.position
          .sub(controls.target)
          .multiplyScalar(factor)
          .add(controls.target);
        controls.update();
      }
    },
  };
}
