import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  // 生产环境通过 FastAPI 在 /static 下托管前端资源
  base: "/static/",
  server: {
    port: 5173,
    host: "0.0.0.0"
  }
});


