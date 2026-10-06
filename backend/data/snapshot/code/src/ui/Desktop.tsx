// Issue #3: 桌面化能力的原型入口。
// 复用现有 Web 前端,只是换一个容器宿主。
export function DesktopShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen w-screen overflow-hidden">
      <div data-tauri-drag-region className="h-8 w-full" />
      {children}
    </div>
  );
}