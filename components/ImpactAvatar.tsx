"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { Fighter, Outcome, Zone } from "@/lib/replay";
import styles from "./ImpactAvatar.module.css";

export interface Feedback {
  defender: Fighter;
  zone: Zone;
  outcome: Outcome;
  nonce: number;
}
interface Props {
  fighter: Fighter;
  counts: Record<Zone, number>;
  feedback: Feedback | null;
  onZone?: (zone: Zone) => void;
  engagement?: boolean;
  label?: string;
}

export function ImpactAvatar({ fighter, counts, feedback, onZone, engagement = false, label }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const state = useRef({ counts, feedback, onZone, engagement });
  const [fallback, setFallback] = useState(false);
  useEffect(() => {
    state.current = { counts, feedback, onZone, engagement };
  }, [counts, feedback, onZone, engagement]);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setFallback(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-hidden", "true");
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
    camera.position.set(0.36, 1.35, 4.3);
    camera.lookAt(0, 1.15, 0);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x4b4f5c, 2.1));
    const light = new THREE.DirectionalLight(0xffffff, 3.1);
    light.position.set(-2, 4, 3);
    scene.add(light);
    const rim = new THREE.DirectionalLight(0xc8dcff, 2);
    rim.position.set(2, 2, -2);
    scene.add(rim);
    const group = new THREE.Group();
    scene.add(group);
    const regions: Record<Zone, THREE.MeshStandardMaterial[]> = {
      head: [],
      body: [],
      leg: [],
    };
    const clickable: THREE.Object3D[] = [];
    function part(position: number[], scale: number[], zone: Zone) {
      const material = new THREE.MeshStandardMaterial({
        color: 0xb7bbc4,
        roughness: 0.5,
        metalness: 0.23,
      });
      regions[zone].push(material);
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(1, 32, 24),
        material,
      );
      mesh.position.set(position[0], position[1], position[2]);
      mesh.scale.set(scale[0], scale[1], scale[2]);
      mesh.userData.zone = zone;
      group.add(mesh);
      clickable.push(mesh);
      return mesh;
    }
    // A neutral, sculpted mannequin. Zones represent coarse contact regions only.
    part([0, 2.02, 0], [0.135, 0.19, 0.125], "head");
    part([0, 1.81, 0], [0.074, 0.092, 0.074], "body");
    part([0, 1.57, 0], [0.25, 0.25, 0.115], "body");
    part([-0.105, 1.6, 0.043], [0.135, 0.145, 0.108], "body");
    part([0.105, 1.6, 0.043], [0.135, 0.145, 0.108], "body");
    part([0, 1.31, 0], [0.175, 0.19, 0.1], "body");
    part([0, 1.08, 0], [0.205, 0.13, 0.12], "body");
    for (const side of [-1, 1]) {
      part([side * 0.275, 1.65, 0], [0.105, 0.115, 0.1], "body");
      const upper = part([side * 0.33, 1.43, 0], [0.08, 0.18, 0.078], "body");
      upper.rotation.z = side * 0.17;
      part([side * 0.36, 1.25, 0], [0.07, 0.075, 0.072], "body");
      const forearm = part(
        [side * 0.375, 1.08, 0.025],
        [0.067, 0.16, 0.063],
        "body",
      );
      forearm.rotation.z = side * 0.08;
      part([side * 0.39, 0.89, 0.04], [0.067, 0.1, 0.055], "body");
      const thigh = part([side * 0.13, 0.8, 0], [0.103, 0.24, 0.105], "leg");
      thigh.rotation.z = side * 0.045;
      part([side * 0.145, 0.55, 0.015], [0.082, 0.082, 0.084], "leg");
      part([side * 0.155, 0.34, 0], [0.074, 0.19, 0.075], "leg");
      part([side * 0.16, 0.125, 0.052], [0.085, 0.048, 0.14], "leg");
    }
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(0.48, 0.48, 0.017, 64),
      new THREE.MeshStandardMaterial({
        color: 0x575c66,
        transparent: true,
        opacity: 0.14,
      }),
    );
    base.position.y = 0.056;
    group.add(base);
    const ringMaterial = new THREE.MeshBasicMaterial({
      color: 0xffb67b,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.15, 0.162, 64),
      ringMaterial,
    );
    scene.add(ring);
    const shieldShape = new THREE.Shape();
    shieldShape.moveTo(0, 0.26);
    shieldShape.lineTo(0.21, 0.17);
    shieldShape.lineTo(0.18, -0.1);
    shieldShape.quadraticCurveTo(0.1, -0.24, 0, -0.29);
    shieldShape.quadraticCurveTo(-0.1, -0.24, -0.18, -0.1);
    shieldShape.lineTo(-0.21, 0.17);
    shieldShape.closePath();
    const shieldMaterial = new THREE.MeshBasicMaterial({
      color: 0x8fcaff,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const shield = new THREE.Mesh(
      new THREE.ShapeGeometry(shieldShape),
      shieldMaterial,
    );
    scene.add(shield);
    const edgeMaterial = new THREE.LineBasicMaterial({
      color: 0xb9e0ff,
      transparent: true,
      opacity: 0,
    });
    const outline = new THREE.LineSegments(
      new THREE.EdgesGeometry(shield.geometry),
      edgeMaterial,
    );
    shield.add(outline);
    const zoneY = { head: 2.02, body: 1.5, leg: 0.62 };
    const pointer = new THREE.Vector2(),
      raycaster = new THREE.Raycaster();
    function hit(event: PointerEvent) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        (-(event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const found = raycaster.intersectObjects(clickable)[0];
      if (found) state.current.onZone?.(found.object.userData.zone as Zone);
    }
    renderer.domElement.addEventListener("pointerup", hit);
    let needsRender = true;
    const observer = new ResizeObserver(() => {
      const rect = host.getBoundingClientRect();
      renderer.setSize(rect.width, rect.height);
      camera.aspect = rect.width / rect.height;
      camera.updateProjectionMatrix();
      needsRender = true;
    });
    observer.observe(host);
    let animation = 0,
      lastFrame = 0,
      lastNonce = -1,
      pulseStart = -10000;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const neutral = new THREE.Color(0xb7bbc4),
      hot = new THREE.Color(0xe7a386);
    let wasAnimating = false;
    let renderedState: typeof state.current | null = null;
    function frame(now: number) {
      animation = requestAnimationFrame(frame);
      if (document.hidden || now - lastFrame < 32) return;
      lastFrame = now;
      const current = state.current,
        active =
          current.feedback?.defender === fighter ? current.feedback : null;
      if (active && active.nonce !== lastNonce) {
        lastNonce = active.nonce;
        pulseStart = now;
      }
      const elapsed = (now - pulseStart) / 1000,
        flashing =
          active &&
          elapsed < 0.9 &&
          (active.outcome === "landed" || active.outcome === "blocked");
      const animating = !!flashing || (current.engagement && !reduced.matches);
      if (!animating && !wasAnimating && renderedState === current && !needsRender) return;
      wasAnimating = animating;
      renderedState = current;
      for (const zone of ["head", "body", "leg"] as Zone[])
        for (const material of regions[zone]) {
          material.color
            .copy(neutral)
            .lerp(hot, Math.min(current.counts[zone] / 4, 1) * 0.68);
          const pulse =
            flashing && active.zone === zone && active.outcome === "landed"
              ? Math.max(0, 1 - elapsed / 0.9)
              : 0;
          // Live engagement is a blue torso glow, distinct from a contact flash.
          const glow = current.engagement && zone === "body";
          material.emissive.set(pulse > 0 ? 0xe9925b : glow ? 0x4d86c9 : 0x000000);
          material.emissiveIntensity = pulse > 0
            ? (reduced.matches ? pulse * 0.25 : pulse * 1.5)
            : glow ? (reduced.matches ? 0.2 : 0.25 + Math.sin(now / 500) * 0.08) : 0;
        }
      ringMaterial.opacity = 0;
      shieldMaterial.opacity = 0;
      edgeMaterial.opacity = 0;
      if (flashing) {
        if (active.outcome === "landed" && !reduced.matches) {
          ring.position.set(0, zoneY[active.zone], 0.24);
          ring.scale.setScalar(1 + elapsed * 2.5);
          ringMaterial.opacity = (1 - elapsed / 0.9) * 0.85;
        }
        if (active.outcome === "blocked") {
          shield.position.set(0, zoneY[active.zone], 0.31);
          shield.rotation.y = reduced.matches
            ? 0
            : Math.max(0, 1 - elapsed * 5) * -0.65;
          shieldMaterial.opacity = (1 - elapsed / 0.9) * 0.24;
          edgeMaterial.opacity = (1 - elapsed / 0.9) * 0.9;
        }
      }
      renderer.render(scene, camera);
      needsRender = false;
    }
    animation = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(animation);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerup", hit);
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh ||
          object instanceof THREE.LineSegments
        ) {
          object.geometry.dispose();
          const mats = Array.isArray(object.material)
            ? object.material
            : [object.material];
          mats.forEach((m) => m.dispose());
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [fighter]);
  return (
    <div
      className={`${styles.stage} avatar-stage`}
      data-engagement={engagement}
      data-feedback={feedback?.defender === fighter ? feedback.outcome : "none"}
      ref={container}
      role="img"
      aria-label={label ?? `Fighter ${fighter} received contacts: head ${counts.head}, body ${counts.body}, legs ${counts.leg}. Use the region buttons below to inspect events.`}
    >
      {fallback && (
        <svg
          viewBox="0 0 160 240"
          className={`${styles.fallback} avatar-fallback`}
          aria-hidden="true"
        >
          <defs>
            <linearGradient id={`body-${fighter}`}>
              <stop stopColor="#858b96" />
              <stop offset=".5" stopColor="#d3d6dc" />
              <stop offset="1" stopColor="#9298a3" />
            </linearGradient>
          </defs>
          <g fill={`url(#body-${fighter})`} stroke="#757b86" strokeWidth=".5">
            <ellipse cx="80" cy="30" rx="14" ry="20" />
            <path d="M65 54 Q80 47 95 54 L104 92 95 133 65 133 56 92Z" />
            <path d="M57 61 45 105 40 137 49 141 60 109 66 67Z M103 61 115 105 120 137 111 141 100 109 94 67Z" />
            <path d="M65 135 61 178 60 221 75 223 79 178 79 136Z M81 136 81 178 85 223 100 221 99 178 95 135Z" />
          </g>
          {(["head", "body", "leg"] as Zone[]).map((zone, i) => (
            <ellipse
              key={zone}
              cx="80"
              cy={[30, 90, 180][i]}
              rx={zone === "head" ? 14 : 22}
              ry={zone === "head" ? 20 : 34}
              fill="#f0a178"
              opacity={Math.min(counts[zone] / 4, 1) * 0.5}
            />
          ))}
        </svg>
      )}
    </div>
  );
}
