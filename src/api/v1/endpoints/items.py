from fastapi import APIRouter, HTTPException

from schemas.item import Item, ItemCreate

router = APIRouter()

# In-memory store — replace with a real DB/service layer
_items: dict[int, Item] = {}
_counter = 0


@router.get("/", response_model=list[Item])
def list_items():
    return list(_items.values())


@router.post("/", response_model=Item, status_code=201)
def create_item(payload: ItemCreate):
    global _counter
    _counter += 1
    item = Item(id=_counter, **payload.model_dump())
    _items[_counter] = item
    return item


@router.get("/{item_id}", response_model=Item)
def get_item(item_id: int):
    item = _items.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int):
    if item_id not in _items:
        raise HTTPException(status_code=404, detail="Item not found")
    del _items[item_id]
