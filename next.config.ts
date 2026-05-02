import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

/** Pin app root so Next does not pick a parent folder when multiple package-lock.json files exist (e.g. ~/ and this repo). */
const projectRoot = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  outputFileTracingRoot: projectRoot,
  experimental: {
    serverActions: {
      bodySizeLimit: "10mb"
    }
  }
};

export default nextConfig;
