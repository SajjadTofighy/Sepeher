import { useState } from "react";
import { api } from "../../api";
import { Modal } from "../../shared/ui/primitives";
import type { Act } from "../../shared/lib/actions";
import type { Incident, IncidentCreation } from "../../types";

export default function ProcessIncidentButton({
  act,
  busy,
  onCreated,
}: {
  act: Act;
  busy: boolean;
  onCreated: (incident: Incident) => void;
}) {
  const [open, setOpen] = useState(false);
  const [longitude, setLongitude] = useState(""),
    [latitude, setLatitude] = useState("");
  const [draft, setDraft] = useState<IncidentCreation>({
    title: "",
    severity: "high",
    lon: 0,
    lat: 0,
    description: "",
  });
  const set = <K extends keyof IncidentCreation>(
    key: K,
    value: IncidentCreation[K],
  ) => setDraft({ ...draft, [key]: value });
  return (
    <>
      <button className="secondary" onClick={() => setOpen(true)}>
        ثبت حادثه فرایندی
      </button>
      {open && (
        <Modal title="ثبت حادثه فرایندی" onClose={() => setOpen(false)}>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const result = await act(
                () =>
                  api<Incident>("/incidents", "POST", {
                    ...draft,
                    lon: Number(longitude),
                    lat: Number(latitude),
                  }),
                "حادثه فرایندی ثبت شد",
              );
              if (result) {
                setOpen(false);
                onCreated(result);
                setDraft({
                  title: "",
                  severity: "high",
                  lon: 0,
                  lat: 0,
                  description: "",
                });
                setLongitude("");
                setLatitude("");
              }
            }}
          >
            <label className="field">
              عنوان حادثه
              <input
                required
                minLength={3}
                maxLength={200}
                value={draft.title}
                onChange={(e) => set("title", e.target.value)}
              />
            </label>
            <label className="field">
              شدت
              <select
                value={draft.severity}
                onChange={(e) =>
                  set(
                    "severity",
                    e.target.value as IncidentCreation["severity"],
                  )
                }
              >
                <option value="critical">بحرانی</option>
                <option value="high">زیاد</option>
                <option value="medium">متوسط</option>
                <option value="low">کم</option>
                <option value="info">اطلاع</option>
              </select>
            </label>
            <div className="form-grid">
              <label className="field">
                طول جغرافیایی
                <input
                  required
                  type="number"
                  step="any"
                  min={-180}
                  max={180}
                  value={longitude}
                  onChange={(e) => setLongitude(e.target.value)}
                />
              </label>
              <label className="field">
                عرض جغرافیایی
                <input
                  required
                  type="number"
                  step="any"
                  min={-85}
                  max={85}
                  value={latitude}
                  onChange={(e) => setLatitude(e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              شرح حادثه
              <textarea
                required
                maxLength={4000}
                value={draft.description}
                onChange={(e) => set("description", e.target.value)}
              />
            </label>
            <button className="primary full" type="submit" disabled={busy}>
              ثبت حادثه
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}
