import { Component, type ErrorInfo, type ReactNode } from "react";
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI error", error, info.componentStack);
  }
  render() {
    if (this.state.failed)
      return (
        <div className="error-boundary">
          <h1>نمایش این بخش با مشکل روبه‌رو شد</h1>
          <p>برای بازگشت به مرکز فرماندهی، صفحه را دوباره بارگذاری کنید.</p>
          <button className="primary" onClick={() => location.reload()}>
            بارگذاری مجدد
          </button>
        </div>
      );
    return this.props.children;
  }
}
