from fastapi import APIRouter

from app.routers.prod_parity import compare_files, validate_upload

router = APIRouter()
router.add_api_route('/compare', compare_files, methods=['POST'], tags=['universal-comparison'])
router.add_api_route('/validate', validate_upload, methods=['POST'], tags=['universal-comparison'])
