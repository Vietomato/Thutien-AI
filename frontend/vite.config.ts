import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Cấu hình Vite
// - alias "@/..." trỏ vào thư mục src (import gọn: import { Button } from "@/components/ui/Button")
// - Backend do nhóm kết nối sau: khai báo địa chỉ trong .env (VITE_API_BASE_URL), xem src/config/api.ts
export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000" },
  },
});
