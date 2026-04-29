"use client";

import { useEffect, useState } from "react";
import { Check, Trash2 } from "lucide-react";
import { api, type Settings } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [garminPw, setGarminPw] = useState("");
  const [orKey, setOrKey] = useState("");
  const [orModel, setOrModel] = useState("");

  function reload() {
    api.settings.get().then((s) => {
      setSettings(s);
      setOrModel(s.openrouter_model ?? "");
    });
  }
  useEffect(reload, []);

  async function saveGarmin() {
    if (!garminPw) return toast.error("Enter a password");
    try {
      await api.settings.setGarminPassword(garminPw);
      toast.success("Garmin password saved to keychain");
      setGarminPw("");
      reload();
    } catch (e: any) { toast.error(e.detail); }
  }
  async function clearGarmin() {
    await api.settings.clearGarminPassword();
    toast.success("Cleared");
    reload();
  }
  async function saveOpenRouter() {
    if (!orKey) return toast.error("Enter an API key");
    try {
      await api.settings.setOpenRouter(orKey, orModel || null);
      toast.success("OpenRouter key saved");
      setOrKey("");
      reload();
    } catch (e: any) { toast.error(e.detail); }
  }
  async function clearOpenRouter() {
    await api.settings.clearOpenRouter();
    toast.success("Cleared");
    reload();
  }

  if (!settings) return <p className="p-8 text-muted-foreground">Loading…</p>;

  return (
    <div className="max-w-2xl mx-auto px-8 py-10">
      <h1 className="text-3xl font-bold mb-1">Settings</h1>
      <p className="text-muted-foreground mb-8">
        Credentials are stored in your OS keychain, never in the database.
      </p>

      <Card className="mb-4">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Garmin password</CardTitle>
              <CardDescription>Required to push workouts to Garmin Connect.</CardDescription>
            </div>
            {settings.has_garmin_password && (
              <Badge variant="secondary"><Check className="h-3 w-3 mr-1" /> set</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="grid gap-1">
            <Label htmlFor="gpw">New password</Label>
            <Input id="gpw" type="password" value={garminPw} onChange={(e) => setGarminPw(e.target.value)} />
          </div>
          <div className="flex gap-2 justify-end">
            {settings.has_garmin_password && (
              <Button variant="ghost" size="sm" onClick={clearGarmin}>
                <Trash2 className="h-4 w-4" /> Remove
              </Button>
            )}
            <Button onClick={saveGarmin}>Save</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>OpenRouter</CardTitle>
              <CardDescription>API key for plan generation. Optional model override.</CardDescription>
            </div>
            {settings.has_openrouter_key && (
              <Badge variant="secondary"><Check className="h-3 w-3 mr-1" /> set</Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="grid gap-1">
            <Label htmlFor="ork">API key</Label>
            <Input id="ork" type="password" value={orKey} onChange={(e) => setOrKey(e.target.value)} placeholder="sk-or-..." />
          </div>
          <div className="grid gap-1">
            <Label htmlFor="orm">Model (optional)</Label>
            <Input id="orm" value={orModel} onChange={(e) => setOrModel(e.target.value)} placeholder="google/gemma-3-27b-it:free" />
          </div>
          <div className="flex gap-2 justify-end">
            {settings.has_openrouter_key && (
              <Button variant="ghost" size="sm" onClick={clearOpenRouter}>
                <Trash2 className="h-4 w-4" /> Remove
              </Button>
            )}
            <Button onClick={saveOpenRouter}>Save</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
