const METRICS = [
  { model: "Baseline 3D U-Net", dsc: 0.6047, hd: 49.9967, iou: 0.5052 },
  { model: "3D Improved U-Net", dsc: 0.6667, hd: 41.6946, iou: 0.5686 },
  { model: "2D Improved U-Net", dsc: 0.6804, hd: 29.3923, iou: 0.5865 },
];

export function ResearchPage() {
  return (
    <div className="page">
      <div className="page-header">
        <h1 style={{ fontSize: "1.6rem" }}>Research: ICH Segmentation</h1>
        <a
          href="https://github.com/Joynnncode/ich-ct-segmentation"
          target="_blank"
          rel="noreferrer"
          className="btn"
        >
          View source on GitHub
        </a>
      </div>

      <div className="disclaimer">
        Case study only — not connected to live inference in this platform. The original
        trained model weights are no longer available, so this section presents the
        dissertation's workflow, methodology, and results rather than a runnable demo. Educational
        / portfolio purposes only, not a validated clinical tool.
      </div>

      <section className="research-section">
        <h2>Overview</h2>
        <p>
          Automated intracranial haemorrhage (ICH) segmentation from non-contrast CT (NCCT)
          images, based on an undergraduate dissertation project. The work explored a deep
          learning workflow using a baseline 3D U-Net and improved U-Net-based refinements aimed
          at one of the main bottlenecks in ICH image analysis: accurately segmenting small
          haemorrhage lesions.
        </p>
      </section>

      <section className="research-section">
        <h2>Workflow</h2>
        <img
          src="/research/ich/workflow_diagram.png"
          alt="ICH segmentation workflow diagram"
          className="research-figure"
        />
        <ol className="research-steps">
          <li>Review image and mask structure across the annotated NCCT volumes</li>
          <li>Build a baseline 3D U-Net workflow for volumetric segmentation</li>
          <li>Identify limitations in small-lesion segmentation</li>
          <li>Apply preprocessing refinements (CT windowing, normalisation, augmentation, resampling, cropping)</li>
          <li>Evaluate improved 3D and 2D workflows against the baseline using quantitative metrics</li>
        </ol>
      </section>

      <section className="research-section">
        <h2>Dataset</h2>
        <div className="stats-grid">
          <div className="stat-tile">
            <div className="stat-label">Volumes</div>
            <div className="stat-value">200</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Training cases</div>
            <div className="stat-value">100</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Closed test cases</div>
            <div className="stat-value">70</div>
          </div>
          <div className="stat-tile">
            <div className="stat-label">Open validation cases</div>
            <div className="stat-value">30</div>
          </div>
        </div>
        <p className="text-muted">
          Annotated 3D NCCT volumes in <code>.nii.gz</code> format, approximately 512 × 512 × 29
          voxels each. The original clinical dataset is not redistributed here due to data access
          and privacy restrictions.
        </p>
      </section>

      <section className="research-section">
        <h2>Results</h2>
        <div className="table-wrap">
          <table className="research-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Dice (DSC)</th>
                <th>Hausdorff Distance</th>
                <th>IoU</th>
              </tr>
            </thead>
            <tbody>
              {METRICS.map((row) => (
                <tr key={row.model}>
                  <td>{row.model}</td>
                  <td>{row.dsc.toFixed(4)}</td>
                  <td>{row.hd.toFixed(4)}</td>
                  <td>{row.iou.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <img
          src="/research/ich/results_summary.png"
          alt="Summary chart of segmentation results"
          className="research-figure"
        />
        <p>
          The improved workflow increased mean Dice from 0.60 to 0.68 versus the baseline 3D
          U-Net, with the largest gains concentrated on small haemorrhage lesions.
        </p>
      </section>

      <section className="research-section">
        <h2>Example visualisation</h2>
        <div className="research-image-row">
          <figure>
            <img
              src="/research/ich/ct_example_placeholder.png"
              alt="Example non-contrast CT slice"
              className="research-figure"
            />
            <figcaption className="text-muted">Example NCCT slice</figcaption>
          </figure>
          <figure>
            <img
              src="/research/ich/segmentation_example_placeholder.png"
              alt="Example segmentation output"
              className="research-figure"
            />
            <figcaption className="text-muted">Segmentation-style output</figcaption>
          </figure>
        </div>
        <p className="text-muted">
          Simplified public-facing visual materials, used to demonstrate workflow structure
          without exposing restricted clinical data.
        </p>
      </section>

      <section className="research-section">
        <h2>Why it isn't live in this platform</h2>
        <p>
          The other segmentation tools on this platform (spleen, liver, kidneys, and other
          organs) run pretrained MONAI Model Zoo bundles. There is no equivalent public bundle for
          ICH segmentation, and the trained weights from this dissertation project were not
          preserved outside the original training environment. Reproducing live inference would
          mean training a new model from scratch on a public dataset with voxel-level haemorrhage
          masks — a separate undertaking from the rest of this platform's plug-in organ models.
        </p>
      </section>
    </div>
  );
}
