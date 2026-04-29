"use client";

import { useState } from "react";
import { Server, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

export function DeletePlanDialog({
  open, onOpenChange, planId, planName, uploadedCount, onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  planId: number;
  planName: string;
  uploadedCount: number;
  onDeleted?: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function deleteLocalOnly() {
    setBusy(true);
    try {
      await api.plans.delete(planId);
      toast.success(`Deleted "${planName}" locally`);
      onOpenChange(false);
      onDeleted?.();
    } catch (e: any) {
      toast.error(e.detail);
    } finally { setBusy(false); }
  }

  async function deleteEverywhere() {
    setBusy(true);
    try {
      const r = await api.plans.unpush(planId);
      if (r.failed.length > 0) {
        toast.error(`Failed to remove ${r.failed.length} from Garmin — plan kept locally`);
        return;
      }
      await api.plans.delete(planId);
      toast.success(`Removed ${r.removed} from Garmin and deleted "${planName}"`);
      onOpenChange(false);
      onDeleted?.();
    } catch (e: any) {
      toast.error(e.detail);
    } finally { setBusy(false); }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete &ldquo;{planName}&rdquo;?</DialogTitle>
          <DialogDescription>
            {uploadedCount > 0
              ? `${uploadedCount} workout${uploadedCount === 1 ? "" : "s"} from this plan ${
                  uploadedCount === 1 ? "is" : "are"
                } currently on your Garmin account. Choose what to do with ${uploadedCount === 1 ? "it" : "them"}.`
              : "No workouts from this plan are currently on Garmin."}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          <button
            type="button"
            onClick={deleteLocalOnly}
            disabled={busy}
            className="flex items-start gap-3 rounded-md border border-input p-4 text-left hover:bg-accent hover:border-accent-foreground/20 transition-colors disabled:opacity-50"
          >
            <Trash2 className="h-5 w-5 mt-0.5 text-muted-foreground shrink-0" />
            <div>
              <div className="font-medium">Delete locally only</div>
              <div className="text-sm text-muted-foreground">
                Removes the plan from this app. Workouts already on Garmin stay there.
              </div>
            </div>
          </button>
          <button
            type="button"
            onClick={deleteEverywhere}
            disabled={uploadedCount === 0 || busy}
            className="flex items-start gap-3 rounded-md border border-destructive/40 p-4 text-left hover:bg-destructive/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
          >
            <Server className="h-5 w-5 mt-0.5 text-destructive shrink-0" />
            <div>
              <div className="font-medium text-destructive">Delete and remove from Garmin</div>
              <div className="text-sm text-muted-foreground">
                Unschedules and deletes every uploaded workout from your Garmin account, then removes the plan locally.
              </div>
            </div>
          </button>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
