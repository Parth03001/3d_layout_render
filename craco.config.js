module.exports = {
  webpack: {
    configure: (webpackConfig) => {
      webpackConfig.resolve.fallback = {
        ...(webpackConfig.resolve.fallback || {}),
        fs: false,
        path: false,
        crypto: false,
        stream: false,
        perf_hooks: false,
        os: false,
        worker_threads: false,
        assert: false,
        util: false,
      };

      // Allow WebAssembly modules
      webpackConfig.experiments = {
        ...(webpackConfig.experiments || {}),
        asyncWebAssembly: true,
      };

      return webpackConfig;
    },
  },
};
