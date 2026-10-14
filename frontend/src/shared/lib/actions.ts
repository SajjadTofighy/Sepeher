export type Act = <T>(
  fn: () => Promise<T>,
  message?: string,
) => Promise<T | null>;
