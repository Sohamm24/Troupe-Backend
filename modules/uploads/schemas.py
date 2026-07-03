from pydantic import BaseModel

class PresignRequest(BaseModel):
    trip_id: str 
    media_context: str
    mime_type: str
    itinerary_slot: str | None = None

class ConfirmUploadRequest(BaseModel):
    trip_id: str
    file_path: str
    media_context: str
    itinerary_slot: str | None = None

class ReplaceImageRequest(BaseModel):
    trip_id: str
    new_file_path: str
    media_context: str
    itinerary_slot: str | None = None
