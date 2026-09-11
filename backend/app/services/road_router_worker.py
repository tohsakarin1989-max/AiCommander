"""Internal stdin/stdout worker; not a user-command execution interface."""
import importlib.metadata
import json
from pathlib import Path
import resource
import sys

from pydantic import ValidationError

from app.services.road_access_policy import VehicleAssumption
from app.services.vehicle_router import RoadCalculationError, RoadLocation, VehicleRouter


def main():
    # Native logging also writes to stdout: constrain its temporary output file.
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
    try:
        data = json.loads(sys.stdin.buffer.read(65537))
        if not isinstance(data, dict):
            raise ValueError('invalid worker input')
        matrix = data.get('operation') == 'matrix'
        reachability = data.get('operation') == 'distance_reachability'
        time_reachability = data.get('operation') == 'time_reachability'
        timed_path = data.get('operation') == 'time_path'
        if time_reachability:
            required = {'operation', 'tiles', 'origin', 'vehicle', 'seconds'}
        elif timed_path:
            required = {'operation', 'tiles', 'start', 'end', 'vehicle', 'seconds'}
        elif reachability:
            required = {'operation', 'tiles', 'origin', 'vehicle', 'distance_m'}
        else:
            required = {'operation', 'tiles', 'sources', 'targets', 'vehicle'} if matrix else {'tiles', 'start', 'end', 'vehicle'}
        if set(data) != required:
            raise ValueError('invalid worker input')
        vehicle = VehicleAssumption.model_validate(data['vehicle'])
        tiles = Path(data['tiles'])
        if not tiles.is_absolute() or not tiles.is_dir():
            raise ValueError('invalid graph directory')
        if time_reachability:
            origin = RoadLocation.model_validate(data['origin'])
            result = VehicleRouter(tiles).time_reachability(origin, vehicle, data['seconds'])
        elif reachability:
            origin = RoadLocation.model_validate(data['origin'])
            result = VehicleRouter(tiles).distance_reachability(origin, vehicle, data['distance_m'])
        elif matrix:
            if (not isinstance(data['sources'], list) or not isinstance(data['targets'], list)
                    or not 1 <= len(data['sources']) <= 10 or not 1 <= len(data['targets']) <= 10):
                raise ValueError('invalid matrix size')
            sources = [RoadLocation.model_validate(point) for point in data['sources']]
            targets = [RoadLocation.model_validate(point) for point in data['targets']]
            result = VehicleRouter(tiles).matrix(sources, targets, vehicle)
        else:
            start = RoadLocation.model_validate(data['start'])
            end = RoadLocation.model_validate(data['end'])
            router = VehicleRouter(tiles)
            result = (router.route_time_prefix(start, end, vehicle, data['seconds']) if timed_path
                      else router.route(start, end, vehicle))
        response = {'result': result}
    except (importlib.metadata.PackageNotFoundError, ImportError):
        response = {'error': 'road_engine_unavailable'}
    except RoadCalculationError as error:
        response = {'error': error.code}
    except (ValueError, TypeError, ValidationError):
        response = {'error': 'road_worker_input_invalid'}
    except Exception:
        response = {'error': 'road_engine_calculation_failed'}
    print(json.dumps(response, allow_nan=False))


if __name__ == '__main__':
    main()
