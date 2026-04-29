"use client";

import { useEffect, useState } from "react";
import { Save, Footprints, Dumbbell, PersonStanding, Plus, X } from "lucide-react";
import { api, type Profile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const SPORT_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ className?: string }>; tint: string }
> = {
  running: { label: "Running", icon: Footprints, tint: "text-blue-400" },
  strength: { label: "Strength", icon: Dumbbell, tint: "text-amber-400" },
  calisthenics: { label: "Calisthenics", icon: PersonStanding, tint: "text-emerald-400" },
};

const SPORTS = ["running", "strength", "calisthenics"];

const COMMON_DISTANCES = [1, 1.5, 5, 10, 21.0975, 42.195];

function parseTime(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3) return null;
  const nums = parts.map((p) => (p === "" ? 0 : Number(p)));
  if (nums.some((n) => Number.isNaN(n))) return null;
  if (parts.length === 1) return Math.max(0, Math.round(nums[0]));
  if (parts.length === 2) return Math.max(0, nums[0] * 60 + nums[1]);
  return Math.max(0, nums[0] * 3600 + nums[1] * 60 + nums[2]);
}
function formatTime(seconds: number | null | undefined): string {
  if (seconds == null || seconds === 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Time input that holds raw user text and only commits on blur/Enter,
 *  so typing "22:30" doesn't get reformatted mid-keystroke. */
function TimeInput({
  seconds,
  onCommit,
  placeholder = "22:30",
}: {
  seconds: number | null | undefined;
  onCommit: (s: number | null) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState(formatTime(seconds));
  // Re-sync if external value changes (e.g. row reordered) AND we're not focused.
  const focusedRef = (typeof window !== "undefined" ? null : null);
  useEffect(() => {
    setText(formatTime(seconds));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);

  function commit() {
    const parsed = parseTime(text);
    if (parsed == null && text.trim() !== "") {
      // invalid input: snap back to last known good value
      setText(formatTime(seconds));
      return;
    }
    onCommit(parsed);
    setText(formatTime(parsed));
  }

  return (
    <Input
      placeholder={placeholder}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          (e.currentTarget as HTMLInputElement).blur();
        }
      }}
      inputMode="numeric"
    />
  );
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    api.profile.get()
      .then(setProfile)
      .catch(() => setProfile({
        name: "",
        garmin_email: null, recent_5k_seconds: null,
        threshold_hr: null, max_hr: null,
        preferred_days: {}, weekly_hours_target: null,
        notes: null,
        enabled_sports: [], sport_profiles: {},
      }));
  }, []);

  if (!profile) return <p className="p-8 text-muted-foreground">Loading…</p>;

  function patch(p: Partial<Profile>) {
    setProfile((prev) => prev ? { ...prev, ...p } : prev);
  }
  function patchSport(sport: string, data: any) {
    setProfile((prev) =>
      prev
        ? {
            ...prev,
            sport_profiles: {
              ...(prev.sport_profiles || {}),
              [sport]: { ...(prev.sport_profiles?.[sport] || {}), ...data },
            },
          }
        : prev,
    );
  }
  function toggleSport(sport: string) {
    if (!profile) return;
    const enabled = profile.enabled_sports.includes(sport)
      ? profile.enabled_sports.filter((s) => s !== sport)
      : [...profile.enabled_sports, sport];
    patch({ enabled_sports: enabled });
  }
  function toggleDay(sport: string, dayIdx: number) {
    if (!profile) return;
    const current = profile.preferred_days?.[sport] ?? [];
    const next = current.includes(dayIdx)
      ? current.filter((d) => d !== dayIdx)
      : [...current, dayIdx].sort();
    patch({
      preferred_days: { ...(profile.preferred_days ?? {}), [sport]: next },
    });
  }

  async function save() {
    if (!profile) return;
    try {
      const updated = await api.profile.update(profile);
      setProfile(updated);
      toast.success("Profile saved");
    } catch (e: any) {
      toast.error(e.detail ?? e.message);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-10">
      <h1 className="text-3xl font-bold mb-1">Profile</h1>
      <p className="text-muted-foreground mb-8">
        Tell the planner what sports you train and where you stand. Used to compute pace zones, prescribe loads, and choose training days.
      </p>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Identity</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={profile.name ?? ""} onChange={(e) => patch({ name: e.target.value })} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="email">Garmin email</Label>
              <Input
                id="email" type="email"
                value={profile.garmin_email ?? ""}
                onChange={(e) => patch({ garmin_email: e.target.value })}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sports</CardTitle>
            <CardDescription>Click to enable. Each enabled sport gets a benchmark form below.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-3">
              {SPORTS.map((sport) => {
                const meta = SPORT_META[sport];
                const Icon = meta.icon;
                const active = profile.enabled_sports.includes(sport);
                return (
                  <button
                    key={sport}
                    type="button"
                    onClick={() => toggleSport(sport)}
                    className={cn(
                      "flex flex-col items-center gap-2 rounded-lg border-2 p-5 transition-all",
                      active
                        ? "border-primary bg-primary/5"
                        : "border-input hover:border-input/60 hover:bg-accent/50",
                    )}
                  >
                    <Icon className={cn("h-7 w-7", active ? meta.tint : "text-muted-foreground")} />
                    <span className={cn("text-sm font-medium", active ? "text-foreground" : "text-muted-foreground")}>
                      {meta.label}
                    </span>
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {profile.enabled_sports.includes("running") && (
          <RunningCard
            data={profile.sport_profiles?.running ?? {}}
            thresholdHr={profile.threshold_hr}
            maxHr={profile.max_hr}
            preferredDays={profile.preferred_days?.running ?? []}
            onPatch={(d) => patchSport("running", d)}
            onPatchHr={(d) => patch(d)}
            onToggleDay={(i) => toggleDay("running", i)}
          />
        )}
        {profile.enabled_sports.includes("strength") && (
          <StrengthCard
            data={profile.sport_profiles?.strength ?? {}}
            preferredDays={profile.preferred_days?.strength ?? []}
            onPatch={(d: any) => patchSport("strength", d)}
            onToggleDay={(i: number) => toggleDay("strength", i)}
          />
        )}
        {profile.enabled_sports.includes("calisthenics") && (
          <CalisthenicsCard
            data={profile.sport_profiles?.calisthenics ?? {}}
            preferredDays={profile.preferred_days?.calisthenics ?? []}
            onPatch={(d: any) => patchSport("calisthenics", d)}
            onToggleDay={(i: number) => toggleDay("calisthenics", i)}
          />
        )}

        <Card>
          <CardHeader>
            <CardTitle>More context</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="hours">Weekly hours target (across all sports)</Label>
              <Input
                id="hours" type="number" step="0.5"
                value={profile.weekly_hours_target ?? ""}
                onChange={(e) => patch({
                  weekly_hours_target: e.target.value ? Number(e.target.value) : null,
                })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="notes">Notes for the planner</Label>
              <Textarea
                id="notes" rows={3}
                placeholder="Injuries, equipment available, race plans, training history…"
                value={profile.notes ?? ""}
                onChange={(e) => patch({ notes: e.target.value })}
              />
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end">
          <Button onClick={save} size="lg">
            <Save className="h-4 w-4" /> Save profile
          </Button>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------- helpers

function DayPicker({ days, onToggle }: { days: number[]; onToggle: (i: number) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {DAYS.map((d, i) => {
        const active = days.includes(i);
        return (
          <button
            key={d}
            type="button"
            onClick={() => onToggle(i)}
            className={cn(
              "px-3 py-1.5 rounded-md text-sm border transition-colors",
              active
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background border-input hover:bg-accent",
            )}
          >
            {d}
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------- running card

function RunningCard({
  data, thresholdHr, maxHr, preferredDays,
  onPatch, onPatchHr, onToggleDay,
}: {
  data: any;
  thresholdHr: number | null;
  maxHr: number | null;
  preferredDays: number[];
  onPatch: (d: any) => void;
  onPatchHr: (d: { threshold_hr?: number | null; max_hr?: number | null }) => void;
  onToggleDay: (i: number) => void;
}) {
  const races: { distance_km: number; seconds: number }[] = data.race_times ?? [];

  function setRace(i: number, patch: Partial<{ distance_km: number; seconds: number }>) {
    const next = [...races];
    next[i] = { ...next[i], ...patch };
    onPatch({ race_times: next });
  }
  function addRace() {
    onPatch({ race_times: [...races, { distance_km: 5, seconds: 0 }] });
  }
  function removeRace(i: number) {
    onPatch({ race_times: races.filter((_, idx) => idx !== i) });
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Footprints className="h-5 w-5 text-blue-400" />
          <CardTitle>Running</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-2">
          <Label>Recent race / time-trial efforts</Label>
          <p className="text-xs text-muted-foreground">
            Add as many distance/time pairs as you want — they drive pace zones.
          </p>
          {races.map((rt, i) => (
            <div key={i} className="flex gap-2 items-center">
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={rt.distance_km}
                onChange={(e) => setRace(i, { distance_km: Number(e.target.value) })}
              >
                {COMMON_DISTANCES.map((d) => (
                  <option key={d} value={d}>
                    {d === 21.0975 ? "Half marathon" : d === 42.195 ? "Marathon" : `${d} km`}
                  </option>
                ))}
              </select>
              <TimeInput
                seconds={rt.seconds}
                onCommit={(s) => setRace(i, { seconds: s ?? 0 })}
              />
              <Button variant="ghost" size="icon" onClick={() => removeRace(i)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addRace} className="w-fit">
            <Plus className="h-4 w-4" /> Add distance
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="grid gap-2">
            <Label htmlFor="lthr">Threshold HR</Label>
            <Input
              id="lthr" type="number"
              value={thresholdHr ?? ""}
              onChange={(e) =>
                onPatchHr({ threshold_hr: e.target.value ? Number(e.target.value) : null })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="maxhr">Max HR</Label>
            <Input
              id="maxhr" type="number"
              value={maxHr ?? ""}
              onChange={(e) => onPatchHr({ max_hr: e.target.value ? Number(e.target.value) : null })}
            />
          </div>
        </div>

        <div className="grid gap-2">
          <Label>Preferred running days</Label>
          <DayPicker days={preferredDays} onToggle={onToggleDay} />
        </div>
      </CardContent>
    </Card>
  );
}

// ------------------------------------------------------ strength card

function StrengthCard({ data, preferredDays, onPatch, onToggleDay }: any) {
  const lifts = data.lifts_1rm ?? {};
  const setLift = (k: string, v: string) =>
    onPatch({ lifts_1rm: { ...lifts, [k]: v ? Number(v) : null } });

  const fields: [string, string][] = [
    ["squat_kg", "Back Squat"],
    ["bench_kg", "Bench Press"],
    ["deadlift_kg", "Deadlift"],
    ["ohp_kg", "Overhead Press"],
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Dumbbell className="h-5 w-5 text-amber-400" />
          <CardTitle>Strength</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-2">
          <Label>1-rep max (kg)</Label>
          <div className="grid grid-cols-2 gap-3">
            {fields.map(([k, label]) => (
              <div key={k} className="grid gap-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Input
                  type="number" placeholder="—"
                  value={lifts[k] ?? ""}
                  onChange={(e) => setLift(k, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-1 max-w-xs">
          <Label htmlFor="age">Training age (years)</Label>
          <Input
            id="age" type="number" step="0.5"
            value={data.training_age_years ?? ""}
            onChange={(e) =>
              onPatch({
                training_age_years: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </div>
        <div className="grid gap-2">
          <Label>Preferred strength days</Label>
          <DayPicker days={preferredDays} onToggle={onToggleDay} />
        </div>
      </CardContent>
    </Card>
  );
}

// -------------------------------------------------- calisthenics card

function CalisthenicsCard({ data, preferredDays, onPatch, onToggleDay }: any) {
  const reps = data.max_reps ?? {};
  const holds = data.max_holds ?? {};
  const setReps = (k: string, v: string) =>
    onPatch({ max_reps: { ...reps, [k]: v ? Number(v) : null } });
  const setHolds = (k: string, v: string) =>
    onPatch({ max_holds: { ...holds, [k]: v ? Number(v) : null } });

  const repFields: [string, string][] = [
    ["pullups", "Pull-ups"],
    ["dips", "Dips"],
    ["pushups", "Push-ups"],
    ["squats", "Body squats"],
    ["pistol_squats", "Pistol squats (per leg)"],
  ];
  const holdFields: [string, string][] = [
    ["l_sit_seconds", "L-sit hold (seconds)"],
    ["handstand_seconds", "Handstand hold (seconds)"],
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <PersonStanding className="h-5 w-5 text-emerald-400" />
          <CardTitle>Calisthenics</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-2">
          <Label>Max reps in one set</Label>
          <div className="grid grid-cols-2 gap-3">
            {repFields.map(([k, label]) => (
              <div key={k} className="grid gap-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Input
                  type="number" placeholder="—"
                  value={reps[k] ?? ""}
                  onChange={(e) => setReps(k, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-2">
          <Label>Max holds</Label>
          <div className="grid grid-cols-2 gap-3">
            {holdFields.map(([k, label]) => (
              <div key={k} className="grid gap-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Input
                  type="number" placeholder="—"
                  value={holds[k] ?? ""}
                  onChange={(e) => setHolds(k, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="grid gap-2">
          <Label>Preferred calisthenics days</Label>
          <DayPicker days={preferredDays} onToggle={onToggleDay} />
        </div>
      </CardContent>
    </Card>
  );
}
