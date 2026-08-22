"use client";

import GlassToggle from "@/components/ui/GlassToggle";

export function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <GlassToggle
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      size="sm"
    />
  );
}
