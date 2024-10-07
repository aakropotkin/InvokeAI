import { IconButton, MenuItem } from '@invoke-ai/ui-library';
import { createSelector } from '@reduxjs/toolkit';
import { useAppDispatch, useAppSelector } from 'app/store/storeHooks';
import { useImageDTOContext } from 'features/gallery/contexts/ImageDTOContext';
import { imageToCompareChanged, selectGallerySlice } from 'features/gallery/store/gallerySlice';
import { memo, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { PiImagesBold } from 'react-icons/pi';

export const ImageMenuItemSelectForCompare = memo(() => {
  const { t } = useTranslation();
  const dispatch = useAppDispatch();
  const imageDTO = useImageDTOContext();
  const selectMaySelectForCompare = useMemo(
    () => createSelector(selectGallerySlice, (gallery) => gallery.imageToCompare?.image_name !== imageDTO.image_name),
    [imageDTO.image_name]
  );
  const maySelectForCompare = useAppSelector(selectMaySelectForCompare);

  const onClick = useCallback(() => {
    dispatch(imageToCompareChanged(imageDTO));
  }, [dispatch, imageDTO]);

  return (
    <IconButton
      as={MenuItem}
      icon={<PiImagesBold />}
      isDisabled={!maySelectForCompare}
      onClick={onClick}
      aria-label={t('gallery.selectForCompare')}
      tooltip={t('gallery.selectForCompare')}
      variant="unstyled"
      colorScheme="base"
      w="min-content"
      display="flex"
      alignItems="center"
      justifyContent="center"
    />
  );
});

ImageMenuItemSelectForCompare.displayName = 'ImageMenuItemSelectForCompare';
