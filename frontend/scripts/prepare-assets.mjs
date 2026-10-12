import { mkdir, copyFile } from "node:fs/promises";
const target = new URL("../public/demo/", import.meta.url);
await mkdir(target, { recursive: true });
await copyFile(
  new URL("../../examples/arcade/measure.mp4", import.meta.url),
  new URL("footage.mp4", target),
);
