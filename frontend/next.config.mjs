/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器内挂载卷文件变更事件不可靠,开发时靠轮询
  webpack: (config) => {
    config.watchOptions = { poll: 1000, aggregateTimeout: 300 };
    return config;
  },
};

export default nextConfig;