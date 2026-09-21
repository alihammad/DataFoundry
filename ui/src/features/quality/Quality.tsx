// Quality feature (feature 007, US5).
import { QualityViews } from "./QualityViews";
import { Observability } from "./Observability";

export function Quality() {
  return (
    <div>
      <h1>Quality</h1>
      <QualityViews />
      <Observability />
    </div>
  );
}