"use client";

import { Container } from "@/components/Container";
import { PageHeading } from "@/components/PageHeading";
import { AlertsCenter } from "@/components/alerts/AlertsCenter";
import { useLocale } from "@/components/LocaleProvider";

export default function AlertsPage() {
  const { t } = useLocale();

  return (
    <Container className="flex flex-col gap-8 py-10">
      <PageHeading eyebrow={t("alertsEyebrow")} title={t("alertsTitle")} description={t("alertsDescription")} />
      <AlertsCenter />
    </Container>
  );
}
