import { Search } from "lucide-react";
export default function SearchBox({
  value,
  set,
}: {
  value: string;
  set: (s: string) => void;
}) {
  return (
    <label className="search-box">
      <Search size={17} />
      <input
        aria-label="جستجو"
        placeholder="جستجو در رکوردها…"
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  );
}
