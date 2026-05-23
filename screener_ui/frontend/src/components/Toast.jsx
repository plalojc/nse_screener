import { useEffect } from "react";
import { X } from "lucide-react";

export function Toast({ message, onClose }) {
  useEffect(() => {
    if (!message) return undefined;

    const timer = window.setTimeout(onClose, 3000);
    const closeOnPointerDown = () => onClose();
    document.addEventListener("pointerdown", closeOnPointerDown);

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("pointerdown", closeOnPointerDown);
    };
  }, [message, onClose]);

  if (!message) return null;

  return (
    <div className="toast" role="status" aria-live="polite" onPointerDown={(event) => event.stopPropagation()}>
      <span>{message}</span>
      <button type="button" className="toastClose" onClick={onClose} title="Close message">
        <X size={14} />
      </button>
    </div>
  );
}
