"use client";

import { useEffect, useState } from "react";
import { Save } from "lucide-react";
import { api, type Profile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function parse5k(value: string): number | null {
  if (!value) return null;
  if (value.includes(":")) {
    const [m, s] = value.split(":");
    return parseInt(m) * 60 + parseInt(s || "0");
  }
  return parseInt(value);
}
function format5k(seconds: number | null): string {
  if (seconds == null) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function ProfilePage() {
  const [profile, setProfile] = useState<Partial<Profile>>({
    preferred_days: { running: [], strength: [] },
  });
  const [loaded, setLoaded] = useState(false);
  const [t5k, setT5k] = useState("");

  useEffect(() => {
    api.profile.get()
      .then((p) => {
        setProfile(p);
        setT5k(format5k(p.recent_5k_seconds));
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  function toggleDay(sport: string, dayIdx: number) {
    const current = profile.preferred_days?.[sport] ?? [];
    const next = current.includes(dayIdx)
      ? current.filter((d) => d !== dayIdx)
      : [...current, dayIdx].sort();
    setProfile({
      ...profile,
      preferred_days: { ...(profile.preferred_days ?? {}), [sport]: next },
    });
  }

  async function save() {
    try {
      const data = { ...profile, recent_5k_seconds: parse5k(t5k) };
      const updated = await api.profile.update(data);
      setProfile(updated);
      toast.success("Profile saved");
    } catch (e: any) {
      toast.error(e.detail ?? e.message);
    }
  }

  if (!loaded) return <p className="p-8 text-muted-foreground">Loading…</p>;

  return (
    <div className="max-w-3xl mx-auto px-8 py-10">
      <h1 className="text-3xl font-bold mb-1">Profile</h1>
      <p className="text-muted-foreground mb-8">
        Used by the planner to compute pace zones and choose training days.
      </p>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Identity</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Name</Label>
              <Input
                id="name"
                value={profile.name ?? ""}
                onChange={(e) => setProfile({ ...profile, name: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="email">Garmin email</Label>
              <Input
                id="email"
                type="email"
                value={profile.garmin_email ?? ""}
                onChange={(e) => setProfile({ ...profile, garmin_email: e.target.value })}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Fitness benchmarks</CardTitle>
            <CardDescription>
              Drives pace and HR zones in generated plans.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-3">
            <div className="grid gap-2">
              <Label htmlFor="t5k">Recent 5k (mm:ss)</Label>
              <Input id="t5k" placeholder="22:30" value={t5k} onChange={(e) => setT5k(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="lthr">Threshold HR</Label>
              <Input
                id="lthr"
                type="number"
                value={profile.threshold_hr ?? ""}
                onChange={(e) =>
                  setProfile({ ...profile, threshold_hr: e.target.value ? Number(e.target.value) : null })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="maxhr">Max HR</Label>
              <Input
                id="maxhr"
                type="number"
                value={profile.max_hr ?? ""}
                onChange={(e) =>
                  setProfile({ ...profile, max_hr: e.target.value ? Number(e.target.value) : null })
                }
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preferred days</CardTitle>
            <CardDescription>
              Pick which days you typically train each sport.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {["running", "strength"].map((sport) => (
              <div key={sport}>
                <Label className="mb-2 inline-block capitalize">{sport}</Label>
                <div className="flex flex-wrap gap-2">
                  {DAYS.map((d, i) => {
                    const active = profile.preferred_days?.[sport]?.includes(i);
                    return (
                      <button
                        key={d}
                        type="button"
                        onClick={() => toggleDay(sport, i)}
                        className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                          active
                            ? "bg-primary text-primary-foreground border-primary"
                            : "bg-background border-input hover:bg-accent"
                        }`}
                      >
                        {d}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>More context</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="hours">Weekly hours target</Label>
              <Input
                id="hours"
                type="number"
                step="0.5"
                value={profile.weekly_hours_target ?? ""}
                onChange={(e) =>
                  setProfile({
                    ...profile,
                    weekly_hours_target: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="notes">Notes for the planner</Label>
              <Textarea
                id="notes"
                rows={3}
                placeholder="Injuries, equipment available, race plans, etc."
                value={profile.notes ?? ""}
                onChange={(e) => setProfile({ ...profile, notes: e.target.value })}
              />
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end">
          <Button onClick={save}>
            <Save className="h-4 w-4" />
            Save profile
          </Button>
        </div>
      </div>
    </div>
  );
}
