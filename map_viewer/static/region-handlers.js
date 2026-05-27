/**
 * createRegionHandlers — factory for the four shared bounds/coords callbacks.
 *
 * Both RegionsActivity and TeamsActivity wire these callbacks to their canvas
 * and detail panel.  Using a factory avoids duplicating the same logic; the
 * only intentional difference is that Teams omits `detail` (no XML-preview
 * update on bounds change) while Regions passes its RegionDetail instance.
 *
 * @param {object}          opts
 * @param {object}          opts.canvas           — MapCanvas instance
 * @param {object}          opts.registry         — RegionRegistry instance
 * @param {object|null}     [opts.detail=null]    — RegionDetail; null = no XML preview
 * @param {object|null}     [opts.sidebar=null]   — RegionSidebar; null = no sidebar rename
 * @param {() => string}    opts.getMapName       — returns the current map slug
 * @param {() => object}    opts.getHistory       — returns the DeletedRegionHistory
 * @returns {{ onBoundsChange, onBoundsSave, onCoordsChange, onCoordsSave, onRenameRegion }}
 */

import { deriveBoundsFromCoords } from "./region-types.js";
import * as api from "./api.js";

export function createRegionHandlers({ canvas, registry, detail = null, sidebar = null, getMapName, getHistory }) {
  return {
    onBoundsChange(node, bounds) {
      canvas.updateRegionBounds(node, bounds);
      detail?.updateXmlPreview(node);
      for (const ancestor of registry.recomputeAncestorBounds(node.id)) {
        canvas.updateRegionBounds(ancestor, ancestor.bounds);
      }
    },

    onBoundsSave(node, bounds) {
      const mapName = getMapName();
      if (!mapName) return;
      api.patchRegion(mapName, node.id, bounds)
        .then(() => getHistory()?.clearRedo())
        .catch(err => console.error("Region save failed:", err));
    },

    onCoordsChange(node, coords) {
      const newBounds = deriveBoundsFromCoords(node.type, coords);
      if (!newBounds) return;
      node.bounds = newBounds;
      canvas.updateRegionBounds(node, newBounds);
      detail?.updateXmlPreview(node);
      for (const ancestor of registry.recomputeAncestorBounds(node.id)) {
        canvas.updateRegionBounds(ancestor, ancestor.bounds);
      }
    },

    onCoordsSave(node, coords) {
      const mapName = getMapName();
      if (!mapName) return;
      api.updateRegionCoords(mapName, node.id, coords)
        .then(res => {
          if (res.bounds) {
            node.bounds = res.bounds;
            canvas.updateRegionBounds(node, res.bounds);
          }
          getHistory()?.clearRedo();
        })
        .catch(err => console.error("Coord save failed:", err));
    },

    onRenameRegion(node, oldId, newId) {
      registry.renameNode(oldId, newId);
      sidebar?.renameNode(oldId, newId);
      canvas.renameNode(oldId, newId);
      canvas.showAnchors(node);
      const mapName = getMapName();
      if (!mapName) return;
      api.renameRegion(mapName, oldId, newId)
        .then(() => getHistory()?.clearRedo())
        .catch(err => console.error("Region rename failed:", err));
    },
  };
}
