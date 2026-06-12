"use client";

import { useEffect, useState } from "react";
import { listVoices } from "@/app/lib/api";

interface Props {
  voiceMode: boolean;
  onToggle: (on: boolean) => void;
  voice: string;
  onVoiceChange: (v: string) => void;
}

export default function VoiceControls({ voiceMode, onToggle, voice, onVoiceChange }: Props) {
  const [voices, setVoices] = useState<string[]>([]);

  useEffect(() => {
    listVoices()
      .then((data) => {
        setVoices(data.voices);
        // Adopt the backend default if the current pick isn't available
        if (data.voices.length && !data.voices.includes(voice)) {
          onVoiceChange(data.voices.includes(data.default) ? data.default : data.voices[0]);
        }
      })
      .catch(() => setVoices([]));
    // Only run on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex items-center gap-2">
      {voiceMode && voices.length > 0 && (
        <select
          value={voice}
          onChange={(e) => onVoiceChange(e.target.value)}
          className="bg-zinc-800 text-zinc-200 text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500 max-w-[120px]"
          title="Cloned voice"
        >
          {voices.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      )}

      <button
        onClick={() => onToggle(!voiceMode)}
        title={voiceMode ? "Voice replies on" : "Voice replies off"}
        className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
          voiceMode
            ? "bg-indigo-600 text-white hover:bg-indigo-500"
            : "bg-zinc-800 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-700"
        }`}
      >
        {voiceMode ? <SpeakerIcon /> : <SpeakerMuteIcon />}
        Voice
      </button>
    </div>
  );
}

function SpeakerIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
      <path d="M13 4.06 8.7 7.5H5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h3.7l4.3 3.44a1 1 0 0 0 1.62-.78V4.84A1 1 0 0 0 13 4.06Z" />
      <path d="M17 8.5a4 4 0 0 1 0 7 1 1 0 0 0 1 1.5 6 6 0 0 0 0-10 1 1 0 1 0-1 1.5Z" />
    </svg>
  );
}

function SpeakerMuteIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
      <path d="M13 4.06 8.7 7.5H5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1h3.7l4.3 3.44a1 1 0 0 0 1.62-.78V4.84A1 1 0 0 0 13 4.06Z" />
      <path d="M16.5 9.5 22 15M22 9.5 16.5 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
