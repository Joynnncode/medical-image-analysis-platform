import { Niivue } from "@niivue/niivue";
import { useEffect, useRef, useState } from "react";
import { apiClient } from "../api/client";

interface Props {
  scanId: string;
  hasMask: boolean;
}

export function NiivueViewer({ scanId, hasMask }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const objectUrls: string[] = [];

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const imageResp = await apiClient.get(`/scans/${scanId}/file`, {
          responseType: "blob",
        });
        const imageUrl = URL.createObjectURL(imageResp.data);
        objectUrls.push(imageUrl);

        const volumes = [
          { url: imageUrl, colormap: "gray", opacity: 1, name: "scan.nii.gz" },
        ];

        if (hasMask) {
          const maskResp = await apiClient.get(`/scans/${scanId}/mask`, {
            responseType: "blob",
          });
          const maskUrl = URL.createObjectURL(maskResp.data);
          objectUrls.push(maskUrl);
          volumes.push({ url: maskUrl, colormap: "red", opacity: 0.5, name: "mask.nii.gz" });
        }

        if (cancelled || !canvasRef.current) return;

        const nv = new Niivue({ backColor: [0.02, 0.03, 0.06, 1] });
        await nv.attachToCanvas(canvasRef.current);
        await nv.loadVolumes(volumes);
      } catch (err) {
        console.error(err);
        if (!cancelled) setError("Failed to load scan volume.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    return () => {
      cancelled = true;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [scanId, hasMask]);

  return (
    <div className="viewer">
      <canvas ref={canvasRef} className="viewer-canvas" />
      {loading && <div className="viewer-status">Loading volume...</div>}
      {error && <div className="viewer-status viewer-status-error">{error}</div>}
    </div>
  );
}
