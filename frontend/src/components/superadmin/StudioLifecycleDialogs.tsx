import { useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { Studio } from "../../types/superAdmin";
import ConfirmModal from "./ConfirmModal";
import { useToast } from "./Toast";

type Kind = "suspend" | "reactivate" | "delete";

/**
 * Delete a suspended studio. By default only an EMPTY studio can be deleted; the checkbox turns on
 * "delete it together with ALL of its data" (clients, albums, photos, videos, stored files), which
 * additionally needs the exact studio name typed. The server enforces both rules too.
 */
function DeleteStudioDialog({
  studio,
  onClose,
  onDeleted,
}: {
  studio: Studio;
  onClose: () => void;
  onDeleted: (withData: boolean, storageFailures: number) => void | Promise<void>;
}) {
  const [withData, setWithData] = useState(false);
  const [typed, setTyped] = useState("");
  const nameOk = typed.trim() === studio.name.trim();
  return (
    <ConfirmModal
      title={`Delete ${studio.name}?`}
      description={
        withData
          ? "This permanently deletes the studio, its login, its logo AND everything it holds: every client, album, photo and video (the database records and the stored files), comments, favourites and download history. The audit history is kept. This cannot be undone."
          : "This permanently deletes the studio, its login and its logo. It only works for an empty studio with no clients, albums or files; to remove a studio that still holds data, tick the box below. The audit history is kept. This cannot be undone."
      }
      confirmLabel={withData ? "Delete studio and all its data" : "Delete studio"}
      danger
      confirmDisabled={withData && !nameOk}
      onClose={onClose}
      onConfirm={async () => {
        const res = await superAdminService.deleteStudio(studio.id, withData ? { deleteData: true, confirmName: typed.trim() } : undefined);
        await onDeleted(withData, res.storage_failures ?? 0);
      }}
    >
      <label className="sa-check">
        <input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} />
        <span>Also permanently delete all of this studio's clients, albums, photos and videos</span>
      </label>
      {withData && (
        <>
          <p className="sa-notice sa-notice--danger" role="alert">
            Clients will lose access to their galleries and every file is removed from storage for good. There is no undo.
          </p>
          <label className="sa-field">
            <span>
              Type the studio name <strong>{studio.name}</strong> to confirm
            </span>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} aria-label="Type the studio name to confirm" />
          </label>
        </>
      )}
    </ConfirmModal>
  );
}

/**
 * The confirmations for suspending, reactivating and deleting a studio, shared by the
 * studios list and the studio detail page. Render `dialogs` once and call the `open…` functions.
 * Delete is only offered for a suspended studio; the server also enforces that. Without the
 * "delete all data" tick it must also hold no clients, albums or files.
 */
export function useStudioLifecycle(onChanged: () => void | Promise<void>, onDeleted?: (studio: Studio) => void) {
  const toast = useToast();
  const [target, setTarget] = useState<{ kind: Kind; studio: Studio } | null>(null);

  let dialogs = null;
  if (target) {
    const { kind, studio } = target;
    dialogs =
      kind === "delete" ? (
        <DeleteStudioDialog
          studio={studio}
          onClose={() => setTarget(null)}
          onDeleted={async (withData, storageFailures) => {
            toast.success(withData ? "Studio and all its data deleted." : "Studio deleted.");
            if (storageFailures) {
              toast.error(`${storageFailures} stored file(s) could not be removed from storage. Run "python -m app.reconcile_orphans" on the server to clean them up.`);
            }
            setTarget(null);
            if (onDeleted) onDeleted(studio);
            else await onChanged();
          }}
        />
      ) : (
        <ConfirmModal
          title={kind === "suspend" ? `Suspend ${studio.name}?` : `Reactivate ${studio.name}?`}
          description={
            kind === "suspend"
              ? "Admins keep read-only access, uploads and edits are blocked, and the studio's clients can no longer open their galleries until you reactivate it."
              : "Admins can upload and edit again, and clients can open their galleries."
          }
          confirmLabel={kind === "suspend" ? "Suspend studio" : "Reactivate studio"}
          danger={kind === "suspend"}
          askReason
          onClose={() => setTarget(null)}
          onConfirm={async (reason) => {
            if (kind === "suspend") await superAdminService.suspendStudio(studio.id, reason);
            else await superAdminService.reactivateStudio(studio.id, reason);
            toast.success(kind === "suspend" ? "Studio suspended." : "Studio reactivated.");
            setTarget(null);
            await onChanged();
          }}
        />
      );
  }

  return {
    dialogs,
    openSuspend: (studio: Studio) => setTarget({ kind: "suspend", studio }),
    openReactivate: (studio: Studio) => setTarget({ kind: "reactivate", studio }),
    openDelete: (studio: Studio) => setTarget({ kind: "delete", studio }),
  };
}
