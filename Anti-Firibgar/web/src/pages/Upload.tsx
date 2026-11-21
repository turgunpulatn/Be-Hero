import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useUpload } from "../api/hooks";
import { BackLink, Button, cx, ErrorText, Footnote, PageTitle, Spinner } from "../components/ui";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";

export default function Upload() {
  const navigate = useNavigate();
  const upload = useUpload();
  const fileRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [name, setName] = useState("");

  const send = (file?: File) => {
    if (!file) return;
    setName(file.name);
    upload.mutate(file, { onSuccess: (doc) => navigate(`/hujjat/${doc.id}/maqsad`) });
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    send(e.dataTransfer.files[0]);
  };

  const inputs = (
    <>
      <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => send(e.target.files?.[0])} />
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => send(e.target.files?.[0])} />
    </>
  );

  if (upload.isPending)
    return (
      <div className="card mx-auto mt-10 max-w-lg p-10 text-center">
        <Spinner className="h-8 w-8" />
        <p className="mt-4 font-medium">Hujjat o‘qilmoqda…</p>
        <p className="mt-1 text-sm text-muted">{name}</p>
        <p className="mt-3 text-xs text-muted">Surat bo‘lsa, matnni aniqlash bir necha soniya oladi.</p>
      </div>
    );

  return (
    <>
      {inputs}
      <BackLink to="/hujjatlar" />
      <div className="mt-4">
        <PageTitle title={<><span className="md:hidden">Hujjatni skanerlash</span><span className="hidden md:inline">Hujjat yuklash</span></>} />
      </div>

      {/* Mobile: camera first */}
      <div className="md:hidden">
        <button
          type="button"
          onClick={() => cameraRef.current?.click()}
          className="flex aspect-[4/5] w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed border-primary/40 bg-panel text-center"
        >
          <svg viewBox="0 0 24 24" className="h-12 w-12 text-primary" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 8a2 2 0 0 1 2-2h2l1.5-2h7L17 6h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
            <circle cx="12" cy="13" r="4" />
          </svg>
          <span className="mt-3 font-medium text-primary">Suratga olish</span>
          <span className="mt-1 px-8 text-sm text-muted">Hujjatning to‘rt burchagi kadrda bo‘lsin.</span>
        </button>
        <ErrorText error={upload.error} />
        <Button variant="secondary" full className="mt-5" onClick={() => fileRef.current?.click()}>
          Fayl yoki surat yuklash
        </Button>
        <Footnote>PDF · JPG · PNG</Footnote>
      </div>

      {/* Desktop: drag & drop */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={cx(
          "hidden flex-col items-center justify-center rounded-2xl border-2 border-dashed px-10 py-24 text-center transition md:flex",
          drag ? "border-primary bg-panel-strong" : "border-primary/30 bg-panel",
        )}
      >
        <p className="text-lg font-medium">Fayl yoki suratni shu yerga tashlang</p>
        <p className="mt-1 text-sm text-muted">yoki kompyuteringizdan tanlang</p>
        <Button className="mt-6" onClick={() => fileRef.current?.click()}>
          Fayl yoki surat yuklash
        </Button>
        <p className="mt-4 text-xs text-muted">PDF · JPG · PNG · 15 MB gacha</p>
      </div>
      <div className="hidden md:block">
        <ErrorText error={upload.error} />
      </div>
    </>
  );
}
