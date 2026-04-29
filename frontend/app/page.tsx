"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Calendar, ChevronRight } from "lucide-react";
import { api, type PlanSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import { toast } from "sonner";

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);

  useEffect(() => {
    api.plans.list().then(setPlans).catch((e) => {
      toast.error(`Failed to load plans: ${e.detail}`);
      setPlans([]);
    });
  }, []);

  return (
    <div className="max-w-5xl mx-auto px-8 py-10">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Training plans</h1>
          <p className="text-muted-foreground mt-1">
            Generate, edit, and push plans to your Garmin watch.
          </p>
        </div>
        <Button asChild>
          <Link href="/plans/new">
            <Plus className="h-4 w-4" />
            New plan
          </Link>
        </Button>
      </div>

      {plans === null && (
        <p className="text-muted-foreground">Loading…</p>
      )}

      {plans?.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="py-16 text-center">
            <Calendar className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
            <p className="font-medium mb-1">No plans yet</p>
            <p className="text-sm text-muted-foreground mb-4">
              Create your first training plan from a goal.
            </p>
            <Button asChild>
              <Link href="/plans/new">Generate a plan</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {plans?.map((p) => (
          <Link key={p.id} href={`/plans/${p.id}`}>
            <Card className="hover:border-primary transition-colors cursor-pointer">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle>{p.name}</CardTitle>
                    <p className="text-sm text-muted-foreground mt-1">
                      {p.goal_text}
                    </p>
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="secondary">
                  {formatDate(p.start_date)} → {formatDate(p.end_date)}
                </Badge>
                <Badge variant="outline">{p.workout_count} workouts</Badge>
                {p.uploaded_count > 0 && (
                  <Badge>{p.uploaded_count} on Garmin</Badge>
                )}
                <Badge variant={p.status === "active" ? "default" : "outline"}>
                  {p.status}
                </Badge>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
