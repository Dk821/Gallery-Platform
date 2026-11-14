import { FormEvent, useEffect, useRef, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { Studio } from "../../types/superAdmin";
import StudioLogoField from "./StudioLogoField";
import { phoneError, sanitizePhoneInput } from "../../utils/phone";

export default function StudioProfileForm({
  studio,
  onSaved,
  onLogoChanged,
}: {
  studio: Studio;
  onSaved: () => void;
  onLogoChanged: (message: string) => void;
}) {
  const [name, setName] = useState(studio.name);
  const [email, setEmail] = useState(studio.contact_email ?? "");
  const [phone, setPhone] = useState(studio.contact_phone ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The last record the fields were synced from. When the studio is refreshed
  // (a saved edit, or a logo change), a field the operator has not touched
  // follows the server, but one they are in the middle of typing is kept.
  const baseRef = useRef(studio);
  useEffect(() => {
    const prev = baseRef.current;
    baseRef.current = studio;
    if (prev.id !== studio.id) {
      setName(studio.name);
      setEmail(studio.contact_email ?? "");
      setPhone(studio.contact_phone ?? "");
      return;
    }
    setName((cur) => (cur === prev.name ? studio.name : cur));
    setEmail((cur) => (cur === (prev.contact_email ?? "") ? (studio.contact_email ?? "") : cur));
    setPhone((cur) => (cur === (prev.contact_phone ?? "") ? (studio.contact_phone ?? "") : cur));
    // Keyed on updated_at, not the object: a refetch that returns the same
    // record must not wipe what the operator is in the middle of typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studio.id, studio.updated_at]);

  const dirty =
    name !== studio.name ||
    email !== (studio.contact_email ?? "") ||
    phone !== (studio.contact_phone ?? "");

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const phoneProblem = phoneError(phone);
    if (phoneProblem) {
      setError(phoneProblem);
      return;
    }
    setBusy(true);
    try {
      await superAdminService.updateStudio(studio.id, {
        name: name.trim(),
        contact_email: email.trim() || null,
        contact_phone: phone.trim() || null,
      });
      // Show what was actually stored (trimmed), so the form is not left "dirty".
      setName(name.trim());
      setEmail(email.trim());
      setPhone(phone.trim());
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={save} className="sa-form-grid">
        {error && (
          <p className="sa-form-error sa-form-grid__full" role="alert">
            {error}
          </p>
        )}
        <label className="sa-field sa-form-grid__full">
          <span>Name</span>
          <input placeholder="Enter studio name" value={name} onChange={(e) => setName(e.target.value)} maxLength={255} required />
        </label>
        <label className="sa-field">
          <span>Contact email</span>
          <input placeholder="Enter email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="sa-field">
          <span>Contact phone</span>
          <input type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(sanitizePhoneInput(e.target.value))} maxLength={20} placeholder="Enter mobile number" autoComplete="tel" />
        </label>
        <StudioLogoField studio={studio} onChanged={onLogoChanged} />
        <div className="sa-form-grid__full sa-form-actions">
          <button type="submit" className="sa-btn sa-btn--dark" disabled={busy || !dirty}>
            {busy ? "Saving…" : "Save details"}
          </button>
        </div>
      </form>
    </>
  );
}
