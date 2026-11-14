import { useCallback, useState } from "react";
import { superAdminService } from "../../services/superAdmin";
import type { StudioAdminRow } from "../../types/superAdmin";
import RowActionsMenu, { RowAction } from "./RowActionsMenu";
import { useAdminDialogs } from "./StudioAdminsPanel";

/**
 * The "Users" button on the studios list. Clicking it shows each of the studio's
 * users with their actions right away (edit, reset password, disable/enable,
 * delete once disabled), plus "Add user" and a link to the full users dialog.
 */
export default function StudioUsersMenu({
  studioId,
  onChanged,
  onManageAll,
}: {
  studioId: number;
  /** Called after any change, so the studios list can refresh. */
  onChanged: () => void;
  /** Opens the full "Users" dialog. */
  onManageAll: () => void;
}) {
  const [admins, setAdmins] = useState<StudioAdminRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAdmins(await superAdminService.listAdmins(studioId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the studio's users.");
    }
  }, [studioId]);

  const d = useAdminDialogs(studioId, () => {
    load();
    onChanged();
  });

  const actions: RowAction[] = [];
  for (const a of admins ?? []) {
    actions.push({ label: a.name, header: true, hint: `${a.email} · ${a.status === "active" ? "Active" : "Disabled"}` });
    actions.push({ label: "Edit user", onSelect: () => d.openEdit(a) });
    actions.push({ label: "Reset password", onSelect: () => d.openReset(a) });
    actions.push({ label: a.status === "active" ? "Disable user" : "Enable user", onSelect: () => d.openStatus(a) });
    actions.push({
      label: "Delete user",
      danger: true,
      disabled: a.status !== "disabled",
      hint: a.status !== "disabled" ? "Disable the user first" : undefined,
      onSelect: () => d.openDelete(a),
    });
  }
  const loaded = admins !== null;
  if (loaded) {
    if (admins.length === 0) actions.push({ label: "No users yet", header: true, hint: "This studio has nobody who can sign in." });
    // A studio has one login: "Add user" only appears when it has none (delete the user to replace them).
    if (admins.length === 0) actions.push({ label: "Add user", onSelect: d.openAdd });
    // With one user everything is already in this menu; the full dialog only helps with several.
    if ((admins?.length ?? 0) > 1) actions.push({ label: "Manage all users…", onSelect: onManageAll });
  }

  return (
    <>
      <RowActionsMenu
        label="Users"
        actions={actions}
        onOpen={() => {
          setAdmins(null);
          load();
        }}
        emptyText={error ?? "Loading…"}
      />
      {d.dialogs}
    </>
  );
}
