"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft, AlertTriangle, Upload, RotateCcw, Trash2,
  Pencil, Check, X,
} from "lucide-react";
import { api, type PlanDetail, type Workout } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDate } from "@/lib/utils";
import { toast } from "sonner";
import Link from "next/link";

const SPORT_COLORS: Record<string, string> = {
  running: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  strength: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  cycling: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

export default function PlanDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = Number(params.id);

  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);

  const reload = useCallback(() => {
    api.plans.get(id).then(setPlan).catch((e) => toast.error(e.detail));
  }, [id]);

  useEffect(() => { reload(); }, [reload]);

  async function push() {
    if (!confirm("Upload all planned workouts to Garmin?")) return;
    setBusy(true);
    try {
      const r = await api.plans.push(id);
      toast.success(`Pushed ${r.uploaded} workouts (${r.skipped} skipped, ${r.failed.length} failed)`);
      reload();
    } catch (e: any) { toast.error(e.detail); }
    finally { setBusy(false); }
  }
  async function unpush() {
    if (!confirm("Remove all uploaded workouts from Garmin?")) return;
    setBusy(true);
    try {
      const r = await api.plans.unpush(id);
      toast.success(`Removed ${r.removed} from Garmin`);
      reload();
    } catch (e: any) { toast.error(e.detail); }
    finally { setBusy(false); }
  }
  async function deletePlan() {
    if (!confirm("Delete this plan locally? (Garmin uploads NOT removed.)")) return;
    try {
      await api.plans.delete(id);
      toast.success("Plan deleted");
      router.push("/");
    } catch (e: any) { toast.error(e.detail); }
  }

  if (!plan) return <p className="p-8 text-muted-foreground">Loading…</p>;

  const uploadedCount = plan.workouts.filter((w) => w.status === "uploaded").length;
  const plannedCount = plan.workouts.filter((w) => w.status === "planned").length;

  // group by week_number
  const byWeek = new Map<number, Workout[]>();
  plan.workouts.forEach((w) => {
    if (!byWeek.has(w.week_number)) byWeek.set(w.week_number, []);
    byWeek.get(w.week_number)!.push(w);
  });

  return (
    <div className="max-w-5xl mx-auto px-8 py-8">
      <Link href="/" className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-4">
        <ArrowLeft className="h-4 w-4 mr-1" /> All plans
      </Link>

      <div className="flex items-start justify-between mb-2">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{plan.name}</h1>
          <p className="text-muted-foreground mt-1">{plan.goal_text}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={unpush} disabled={busy || uploadedCount === 0}>
            <RotateCcw className="h-4 w-4" /> Unpush
          </Button>
          <Button onClick={push} disabled={busy || plannedCount === 0}>
            <Upload className="h-4 w-4" /> Push to Garmin
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-6 text-sm">
        <Badge variant="secondary">{formatDate(plan.start_date)} → {formatDate(plan.end_date)}</Badge>
        <Badge variant="outline">{plan.workouts.length} workouts</Badge>
        {uploadedCount > 0 && <Badge>{uploadedCount} on Garmin</Badge>}
      </div>

      {plan.warnings.length > 0 && (
        <Card className="mb-6 border-amber-500/40 bg-amber-500/5">
          <CardContent className="pt-6">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-400 mt-0.5" />
              <div>
                <p className="font-medium mb-1">Planner warnings</p>
                <ul className="text-sm text-muted-foreground space-y-0.5">
                  {plan.warnings.map((w, i) => (
                    <li key={i}>
                      <span className="text-amber-400">[{w.severity}]</span> {w.message}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-6">
        {[...byWeek.keys()].sort((a, b) => a - b).map((week) => (
          <div key={week}>
            <h2 className="text-sm font-semibold text-muted-foreground mb-2">
              Week {week}
            </h2>
            <div className="space-y-2">
              {byWeek.get(week)!.map((w) =>
                editing === w.id ? (
                  <WorkoutEditor key={w.id} workout={w} onClose={() => { setEditing(null); reload(); }} />
                ) : (
                  <WorkoutRow key={w.id} workout={w} onEdit={() => setEditing(w.id)} onDelete={() => reload()} />
                ),
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-12 pt-6 border-t">
        <Button variant="ghost" className="text-destructive hover:bg-destructive/10" onClick={deletePlan}>
          <Trash2 className="h-4 w-4" /> Delete plan
        </Button>
      </div>
    </div>
  );
}

function WorkoutRow({ workout, onEdit, onDelete }: { workout: Workout; onEdit: () => void; onDelete: () => void }) {
  const sportColor = SPORT_COLORS[workout.sport] ?? "bg-secondary";
  const isUploaded = workout.status === "uploaded";

  async function del() {
    if (!confirm(`Delete "${workout.title}"?`)) return;
    try {
      await api.workouts.delete(workout.id);
      toast.success("Deleted");
      onDelete();
    } catch (e: any) { toast.error(e.detail); }
  }

  return (
    <Card className="hover:border-primary/40 transition-colors">
      <CardContent className="py-3 px-4 flex items-center gap-4">
        <div className="text-xs text-muted-foreground w-16 shrink-0">
          {formatDate(workout.date)}
        </div>
        <div className={`px-2 py-0.5 rounded text-xs font-medium border ${sportColor}`}>
          {workout.sport}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium truncate">{workout.title}</div>
          <div className="text-xs text-muted-foreground truncate">
            {workout.primitive_type} · {Object.entries(workout.primitive_params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ").slice(0, 80)}
          </div>
        </div>
        {isUploaded && <Badge>on Garmin</Badge>}
        <Button variant="ghost" size="icon" onClick={onEdit} disabled={isUploaded} title={isUploaded ? "Unpush to edit" : "Edit"}>
          <Pencil className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={del} disabled={isUploaded} title={isUploaded ? "Unpush to delete" : "Delete"}>
          <Trash2 className="h-4 w-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

function WorkoutEditor({ workout, onClose }: { workout: Workout; onClose: () => void }) {
  const [title, setTitle] = useState(workout.title);
  const [date, setDate] = useState(workout.date);
  const [paramsText, setParamsText] = useState(JSON.stringify(workout.primitive_params, null, 2));
  const [description, setDescription] = useState(workout.description ?? "");

  async function save() {
    let params;
    try { params = JSON.parse(paramsText); }
    catch { return toast.error("Invalid JSON in params"); }
    try {
      await api.workouts.update(workout.id, {
        title, date, description, primitive_params: params,
      });
      toast.success("Saved");
      onClose();
    } catch (e: any) { toast.error(e.detail); }
  }

  return (
    <Card className="border-primary">
      <CardHeader className="pb-3">
        <div className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
          Editing · {workout.primitive_type}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2 grid gap-1">
            <Label htmlFor="title">Title</Label>
            <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="date">Date</Label>
            <Input id="date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="params">Primitive params (JSON)</Label>
          <Textarea id="params" rows={6} className="font-mono text-xs" value={paramsText} onChange={(e) => setParamsText(e.target.value)} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="desc">Description</Label>
          <Textarea id="desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}><X className="h-4 w-4" /> Cancel</Button>
          <Button onClick={save}><Check className="h-4 w-4" /> Save</Button>
        </div>
      </CardContent>
    </Card>
  );
}
