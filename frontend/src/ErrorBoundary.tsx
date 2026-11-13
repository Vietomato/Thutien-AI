import { Component, type ReactNode } from "react";

/** Catches a crash while drawing a page and shows a message with a retry, instead of a blank screen. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() { return { failed: true }; }

  componentDidCatch(error: unknown) { console.error("Page failed to draw", error); }

  render() {
    if (!this.state.failed) return this.props.children;
    return <div className="alert alert-danger" role="alert" style={{ margin: "24px 0" }}>
      <span>Trang này gặp lỗi khi hiển thị. Các trang khác vẫn dùng được.</span>
      <button className="btn btn-sm" onClick={() => this.setState({ failed: false })}>Thử lại</button>
    </div>;
  }
}
