/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: {
    // Linting runs via `npm run lint`; built-in build lint is kept.
    ignoreDuringBuilds: false,
  },
};

export default nextConfig;